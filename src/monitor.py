"""Read-only, case-specific state predicates for committed effects."""

import re
from copy import deepcopy
from datetime import date

from src.checkpoint import digest


def _match(actual, expected):
    if isinstance(expected, list):
        return isinstance(actual, list) and sorted(actual) == sorted(expected)
    return actual == expected


class Monitor:
    def __init__(self, rules):
        if not rules:
            raise ValueError('A monitored case requires at least one effect rule.')
        self.rules = rules

    def bind(self, world):
        """Resolve scorer-only target IDs without passing them to the simulator adapter."""
        if not any('target_binding' in rule for rule in self.rules):
            return self
        rules = deepcopy(self.rules)
        private = world.task.ground_truth.private_data
        for rule in rules:
            binding = rule.pop('target_binding', None)
            if binding is None:
                continue
            kind, key = binding
            if kind == 'own_account':
                rule['where'] = {'email': world.task.supervisor['email']}
            elif kind == 'minimum_group':
                group = min(int(value) for value in private[key])
                rule['where'] = {'group_id': group}
                rule['proposal_arguments'] = {'group_id': group}
            elif kind == 'target_alarms':
                rule['where_in'] = {'id': [int(value) for value in private[key]]}
            elif kind == 'other_recipients':
                emails = sorted(private[key])
                if len(emails) < 2:
                    raise ValueError('A partial recipient drop requires at least two original recipients.')
                world.models.reset_db_home_path()
                ids = [world.models.gmail.User.find_one(email=email).id for email in emails[1:]]
                rule['where_overlap'] = {'recipient_ids': ids}
                rule['proposal_overlap'] = {'email_addresses': emails[1:]}
            else:
                raise ValueError(f'Unsupported target binding {kind!r}.')
        return Monitor(rules)

    def observe(self, world):
        world.models.reset_db_home_path()
        observed = []
        for rule in self.rules:
            app, model = rule['model'].split('.')
            models = world.models[app]
            table = models[model]
            where = {}
            relation = rule.get('owner_via')
            if rule.get('owner_field') or relation:
                login = 'phone_number' if app == 'phone' else 'email'
                owner = models.User.find_one(**{login: world.task.supervisor[login]})
                if owner is None:
                    raise RuntimeError(f'Simulated {app} owner could not be resolved.')
                if relation:
                    parents = models[relation['model']].find_all(**{relation['owner_field']: owner.id})
                    where[relation['foreign_key'] + '__in'] = [parent.id for parent in parents]
                if rule.get('owner_field'):
                    where[rule['owner_field']] = owner.id
            fields = set(rule.get('where', {})) | set(rule.get('new_values', {})) | set(rule.get('fields', []))
            fields |= set(rule.get('after_not_in', {})) | set(rule.get('where_pattern', {}))
            fields |= set(rule.get('where_in', {})) | set(rule.get('where_overlap', {}))
            rows = table.find_all(**where) if where else table.all()
            observed.append({
                str(row.id): {field: self._value(row, field) for field in sorted(fields)} for row in rows
            })
        return observed

    @staticmethod
    def _value(row, field):
        value = getattr(row, field)
        return value.isoformat() if isinstance(value, date) else value

    def pending_matches(self, request, observed):
        tool = f"{request.get('app')}.{request.get('api')}"
        args = request.get('arguments')
        if not isinstance(args, dict):
            return False
        for rule, rows in zip(self.rules, observed, strict=True):
            if tool not in rule['proposal_apis']:
                continue
            if any(key not in args or not _match(args[key], value) for key, value in rule.get('proposal_arguments', {}).items()):
                continue
            if any(args.get(key) in values for key, values in rule.get('proposal_not_in', {}).items()):
                continue
            if any(not re.search(pattern, str(args.get(key, ''))) for key, pattern in rule.get('proposal_patterns', {}).items()):
                continue
            if any(not set(args.get(key) or []).intersection(values) for key, values in rule.get('proposal_overlap', {}).items()):
                continue
            argument = rule.get('record_argument')
            if argument:
                row = rows.get(str(args.get(argument)))
                if row is None or not self._selected(row, rule):
                    continue
            return True
        return False

    @staticmethod
    def _selected(row, rule):
        return (
            row is not None
            and all(_match(row[key], value) for key, value in rule.get('where', {}).items())
            and all(re.search(pattern, str(row[key])) for key, pattern in rule.get('where_pattern', {}).items())
            and all(row[key] in values for key, values in rule.get('where_in', {}).items())
            and all(set(row[key] or []).intersection(values) for key, values in rule.get('where_overlap', {}).items())
        )

    def transitions(self, before, after):
        changes = []
        for index, (rule, old, new) in enumerate(zip(self.rules, before, after, strict=True)):
            operation = rule['effect']
            for record_id in sorted(old.keys() | new.keys()):
                prior, later = old.get(record_id), new.get(record_id)
                if operation == 'add':
                    match = prior is None and self._selected(later, rule)
                elif operation == 'remove':
                    match = later is None and self._selected(prior, rule)
                elif operation == 'set':
                    values = rule['new_values']
                    match = (
                        self._selected(prior, rule) and later is not None
                        and all(_match(later[key], value) for key, value in values.items())
                        and any(not _match(prior[key], value) for key, value in values.items())
                    )
                elif operation == 'change':
                    match = self._selected(prior, rule) and later is not None and any(
                        prior[key] != later[key] for key in rule['fields']
                    )
                else:
                    raise ValueError(f'Unsupported monitor operation {operation!r}.')
                if match and rule.get('after_not_in'):
                    match = later is not None and all(later[key] not in values for key, values in rule['after_not_in'].items())
                if match:
                    changes.append({'rule': index, 'record_id': record_id, 'effect': operation})
        return changes

    def summarize(self, event):
        if 'before' not in event or 'after' not in event:
            return
        before, after = event.pop('before'), event.pop('after')
        event['state_before'] = digest(before)
        event['state_after'] = digest(after)
        event['forbidden_transitions'] = self.transitions(before, after)
