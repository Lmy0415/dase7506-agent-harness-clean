"""Validate remaining plans and apply local edits without scoring information."""

import json

MAX_STEPS = 20
MAX_STEP_CHARS = 500


def _read_object(text, key):
    def reject_duplicates(pairs):
        result = {}
        for name, value in pairs:
            if name in result:
                raise ValueError(f'Duplicate JSON key {name!r}.')
            result[name] = value
        return result

    obj = json.loads(text, object_pairs_hook=reject_duplicates)
    if not isinstance(obj, dict) or set(obj) != {key}:
        raise ValueError(f'Expected one top-level field, {key!r}.')
    return obj[key]


def _steps(value):
    if not isinstance(value, list) or len(value) > MAX_STEPS:
        raise ValueError(f'Expected a list of at most {MAX_STEPS} steps.')
    if any(not isinstance(step, str) or not step.strip() or len(step) > MAX_STEP_CHARS for step in value):
        raise ValueError(f'Steps must be nonempty strings up to {MAX_STEP_CHARS} characters.')
    return [step.strip() for step in value]


def full_plan(text):
    """Parse B's remaining plan in the same format produced by a local revision."""
    return _steps(_read_object(text, 'steps'))


def initial_plan(text):
    """Assign stable IDs to the plan created before the interruption."""
    return [{'id': index, 'text': step} for index, step in enumerate(full_plan(text), 1)]


def local_revision(old_plan, text):
    """Apply C's edits while preserving untouched steps and dependency order."""
    edits = _read_object(text, 'edits')
    if not isinstance(edits, list) or len(edits) > len(old_plan):
        raise ValueError('Expected a list with at most one edit per old step.')
    old_ids = {step['id'] for step in old_plan}
    by_id = {}
    for edit in edits:
        if not isinstance(edit, dict):
            raise ValueError('Every edit must be a JSON object.')
        step_id = edit.get('id')
        if type(step_id) is not int or step_id not in old_ids or step_id in by_id:
            raise ValueError('Every edit must address a unique ID from the old plan.')
        operation = edit.get('op')
        if operation == 'replace' and set(edit) == {'id', 'op', 'steps'}:
            replacements = _steps(edit['steps'])
            if not replacements:
                raise ValueError('Use delete to remove a step.')
            by_id[step_id] = replacements
        elif operation == 'delete' and set(edit) == {'id', 'op'}:
            by_id[step_id] = []
        elif operation != 'keep' or set(edit) != {'id', 'op'}:
            raise ValueError('Expected keep, delete or replace with its applicable fields.')
        else:
            by_id[step_id] = None

    result = []
    for step in old_plan:
        replacements = by_id.get(step['id'])
        if replacements is None:
            result.append(step['text'])
        else:
            result.extend(replacements)
    return _steps(result)
