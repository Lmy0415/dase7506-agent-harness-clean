"""Conservative normalization and local validation of visible execution state."""

import json
import re
from collections import defaultdict

from src.intent_revision import INTENT_PROMPT, packet, shows_outcome
from src.strategies import _steps, local_revision

C5_PROMPT = INTENT_PROMPT + (
    ' Use original step numbers and e-prefixed receipt IDs, never database object IDs. '
    'Put multiple receipts for one step in one row. A read or draft cannot establish the '
    'completion of a different operation. Leave evidence empty when the relation is unclear.'
)

READ = {'read', 'find', 'search', 'check', 'look', 'identify', 'retrieve', 'inspect', 'show',
        'list', 'locate', 'view', 'review', 'get', 'determine'}
WRITE = {
    'send': {'send', 'reply', 'forward', 'text', 'email', 'deliver'},
    'draft': {'draft'},
    'request': {'request'},
    'pay': {'pay', 'payment', 'transfer', 'transaction'},
    'add': {'add', 'create', 'save', 'record', 'write', 'attach'},
    'remove': {'delete', 'remove', 'cancel', 'unfollow'},
    'update': {'update', 'change', 'edit', 'rename', 'set'},
    'like': {'like'},
    'move': {'move'},
    'download': {'download', 'export'},
    'complete': {'finish', 'complete', 'submit', 'report', 'answer'},
}
API_ACTION = {
    'create_payment_request': 'request', 'create_transaction': 'pay',
    'send_email_from_draft': 'send', 'upload_attachments_to_draft': 'add',
    'update_draft': 'draft', 'create_draft': 'draft',
}
STOP = {'the', 'and', 'for', 'with', 'from', 'that', 'this', 'only', 'all', 'using',
        'needed', 'correct', 'appropriate', 'original', 'required', 'relevant',
        'final', 'related', 'matching', 'target', 'mine', 'selected'}


def step_id(value, old_ids):
    if isinstance(value, str) and re.fullmatch(r'[0-9]{1,6}', value):
        value = int(value)
    if type(value) is not int or value not in old_ids:
        raise ValueError('expected an existing numbered step')
    return value


def normalized_packet(text, old_plan):
    """Normalize representation only. Used for the separate offline ablation."""
    value = packet(text, ('active', 'revoked', 'uncertain', 'evidence', 'edits'))
    old_ids = {step['id'] for step in old_plan}
    for module in ('evidence', 'edits'):
        if not isinstance(value[module], list):
            raise ValueError(f'{module} must be a list')
        for item in value[module]:
            if not isinstance(item, list) or not item:
                raise ValueError(f'invalid {module} row')
            item[0] = step_id(item[0], old_ids)
    grouped = {}
    for item in value['evidence']:
        if len(item) != 3 or item[1] not in ('done', 'partial') or not isinstance(item[2], list) or not item[2]:
            raise ValueError('invalid evidence row')
        sid, status, refs = item
        if any(not isinstance(ref, str) for ref in refs):
            raise ValueError('invalid receipt ID')
        if sid in grouped and grouped[sid][1] != status:
            raise ValueError('conflicting evidence statuses')
        grouped.setdefault(sid, [sid, status, []])[2].extend(refs)
    value['evidence'] = [[sid, status, list(dict.fromkeys(refs))] for sid, status, refs in grouped.values()]
    return value


def terms(text):
    return {word.rstrip('s') for word in re.findall(r'\b[a-z][a-z0-9]{2,}\b', text.lower())
            if word not in STOP}


def action_for(step):
    for word in re.findall(r'[a-z]+', step.lower()):
        if word in READ:
            return 'read'
        matches = [kind for kind, verbs in WRITE.items() if word in verbs]
        if matches:
            return matches[0]
    return None


def evidence_supports(entry, step, status):
    """Only infer completion for a matching operation and visible object evidence."""
    if entry['status'] != 'request_accepted' or not entry['result']:
        return False
    api = entry['api'].split('.')[-1]
    action = API_ACTION.get(api) or action_for(api.replace('_', ' '))
    expected = action_for(step)
    if expected is None or action != expected or not shows_outcome(entry, step):
        return False
    # Explicit literal target identities must match. Unknown compound completion stays pending.
    literal_values = re.findall(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', step)
    literal_values.extend(re.findall(r'["“]([^"”]+)["”]', step))
    literal_values.extend(re.findall(r'\b(?:to|for|from)\s+([A-Z][a-z]+(?: [A-Z][a-z]+)*)\b', step))
    literal_values.extend(re.findall(r'\b(?:id|number)\s*#?\s*(\d+)\b', step, flags=re.I))
    observed = json.dumps([entry['arguments'], entry['result']], ensure_ascii=False).lower()
    if literal_values and not all(re.search(r'(?<![\w])' + re.escape(value.lower()) + r'(?![\w])', observed)
                                  for value in literal_values):
        return False
    if status == 'done' and re.search(r'\b(?:every|all|each|then|afterward)\b|;\s*\w', step, re.I):
        return False
    common = terms(step) & terms(entry['api'].replace('_', ' ') + ' ' + observed)
    verbs = set().union(READ, *WRITE.values())
    return bool(literal_values or common - verbs)


def _intent(value):
    active = value.get('active')
    if not isinstance(active, list) or not 1 <= len(active) <= 12:
        raise ValueError('expected an active requirement')
    entries = []
    for row in active:
        if not isinstance(row, list) or len(row) != 2 or row[0] not in ('o', 'u'):
            raise ValueError('active requirement must have source o or u')
        entries.append({'source': 'original_user' if row[0] == 'o' else 'latest_user_update',
                        'text': _steps([row[1]])[0]})
    revoked = _steps(value.get('revoked'))
    uncertain = _steps(value.get('uncertain'))
    if {e['text'].casefold() for e in entries} & {e.casefold() for e in revoked}:
        raise ValueError('the same requirement is active and revoked')
    return {'version': 2, 'active': entries,
            'revoked': [{'text': text, 'source': 'latest_user_update'} for text in revoked],
            'uncertain': [{'text': text, 'source': 'unresolved'} for text in uncertain]}


def _edit_list(rows, old_plan, old_ids):
    if not isinstance(rows, list):
        raise ValueError('edits must be a list')
    edits = []
    for index, row in enumerate(rows):
        if not isinstance(row, list) or len(row) not in (2, 3):
            raise ValueError(f'edits[{index}] must be a two- or three-field edit')
        try:
            sid = step_id(row[0], old_ids)
        except ValueError as error:
            raise ValueError(f'edits[{index}][0]: {error}') from error
        edit = {'id': sid, 'op': row[1]}
        if len(row) == 3:
            edit['steps'] = row[2]
        edits.append(edit)
    local_revision(old_plan, json.dumps({'edits': edits}))
    return {edit['id']: edit for edit in edits}


def inspect_state(text, old_plan, ledger):
    """Return state plus per-module diagnostics. Scoring data are never an input."""
    fields = {'active', 'revoked', 'uncertain', 'evidence', 'edits'}
    empty_revision = {'mode': 'fallback', 'state': None,
                      'modules': {'intent': False, 'evidence': False, 'edits': False},
                      'issues': [], 'accepted_evidence': 0, 'downgraded_steps': []}
    try:
        value = packet(text, fields)
    except ValueError as error:
        empty_revision['issues'].append(f'JSON envelope: {error}')
        return empty_revision

    issues = []
    by_step = {step['id']: step['text'] for step in old_plan}
    offered = {item['id']: item for item in ledger if item['api'] != 'find_api'
               and item['status'] in ('request_accepted', 'partial_response')}
    offered = dict(list(offered.items())[-12:])
    try:
        intent = _intent(value)
    except ValueError as error:
        issues.append(f'intent: {error}')
        intent = None
    try:
        edits = _edit_list(value['edits'], old_plan, by_step)
    except ValueError as error:
        issues.append(f'edits: {error}')
        edits = None

    evidence_issues = []
    accepted = {}
    grouped = defaultdict(list)
    bad = set()
    rows = value['evidence']
    if not isinstance(rows, list):
        rows = []
        evidence_issues.append('evidence: expected a list')
    for index, row in enumerate(rows):
        if not isinstance(row, list) or len(row) != 3:
            evidence_issues.append(f'evidence[{index}]: expected step, status, receipt list')
            continue
        try:
            sid = step_id(row[0], by_step)
        except ValueError as error:
            evidence_issues.append(f'evidence[{index}][0]: {error}')
            continue
        status, refs = row[1:]
        if (status not in ('done', 'partial') or not isinstance(refs, list) or not refs
                or any(not isinstance(ref, str) or ref not in offered for ref in refs)):
            evidence_issues.append(f'evidence[{index}]: invalid status or unsupported receipt ID')
            bad.add(sid)
            continue
        grouped[sid].append((status, refs))
    for sid, items in grouped.items():
        statuses = {status for status, _ in items}
        if sid in bad or len(statuses) != 1:
            evidence_issues.append(f'evidence step {sid}: inconsistent evidence')
            bad.add(sid)
            continue
        status = next(iter(statuses))
        refs = list(dict.fromkeys(ref for _, group in items for ref in group))
        matching = [ref for ref in refs if evidence_supports(offered[ref], by_step[sid], status)]
        if len(matching) != len(refs):
            evidence_issues.append(f'evidence step {sid}: receipt does not establish the requested operation')
            bad.add(sid)
            continue
        accepted[sid] = (status, matching)
    issues.extend(evidence_issues)

    plan = []
    if edits is not None:
        for step in old_plan:
            sid = step['id']
            status, refs = accepted.get(sid, ('unknown' if sid in bad else 'pending', []))
            edit = edits.get(sid, {'op': 'keep'})
            # Do not remove an uncertain step solely on the back of rejected completion evidence.
            if sid in bad and edit['op'] == 'delete':
                edit = {'op': 'keep'}
                issues.append(f'edits step {sid}: retained after invalid completion evidence')
            if edit['op'] != 'keep' and status != 'done':
                status = 'cancelled'
            plan.append({**step, 'status': status, 'evidence_refs': refs})
            plan.extend({'id': f'{sid}.{i}', 'text': text, 'status': 'pending', 'evidence_refs': []}
                        for i, text in enumerate(edit.get('steps', []), 1))
    usable_plan = edits is not None and bool(edits)
    usable = intent is not None or usable_plan
    mode = ('full' if not issues else 'partial') if usable else 'fallback'
    neutral = {'version': 2, 'active': [], 'revoked': [], 'uncertain': []}
    return {
        'mode': mode,
        'state': {'intent': intent or neutral, 'execution': ledger, 'plan': plan} if usable else None,
        'modules': {'intent': intent is not None, 'evidence': not evidence_issues, 'edits': edits is not None},
        'issues': issues, 'accepted_evidence': len(accepted), 'downgraded_steps': sorted(bad),
    }
