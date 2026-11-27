import json

import pytest

from src.guard_v5 import evaluate, guard_rule
from src.intent_v5 import inspect_state, normalized_packet


PLAN = [{'id': 1, 'text': 'Find the draft'},
        {'id': 2, 'text': 'Send email to Alice'},
        {'id': 3, 'text': 'Keep the note'}]


def packet(evidence, edits=None):
    return json.dumps({'active': [['o', 'Keep the note']], 'revoked': ['Send email to Alice'],
                       'uncertain': [], 'evidence': evidence, 'edits': edits or []})


def receipt(rid, api, result, status='request_accepted', **arguments):
    return {'id': rid, 'api': api, 'arguments': arguments, 'result': result, 'status': status}


def test_c5_normalizes_only_step_fields_and_merges_exact_claims():
    text = packet([['2', 'done', ['e1']], [2, 'done', ['e1', 'e2']]], [['3', 'keep']])
    ledger = [receipt(ref, 'gmail.send_email', {'email_id': i},
                      email_addresses=['alice@example.test']) for i, ref in enumerate(('e1', 'e2'), 1)]
    assert normalized_packet(text, PLAN)['evidence'] == [[2, 'done', ['e1', 'e2']]]
    report = inspect_state(text, PLAN, ledger)
    assert report['mode'] == 'full'
    assert report['state']['plan'][1]['evidence_refs'] == ['e1', 'e2']
    for value in (False, 2.0, '9'):
        with pytest.raises(ValueError, match='existing numbered step'):
            normalized_packet(packet([], [[value, 'keep']]), PLAN)


@pytest.mark.parametrize(('evidence', 'ledger'), [
    ([[2, 'done', ['17']]], [receipt('e1', 'gmail.send_email', {'email_id': 17})]),
    ([[2, 'done', ['e1']]], [receipt('e1', 'gmail.send_email', {}, 'pending')]),
    ([[2, 'done', ['e1']]], [receipt('e1', 'gmail.send_email', {}, 'rejected_or_unverified')]),
    ([[2, 'done', ['e1']]], [receipt('e1', 'gmail.create_draft', {'draft_id': 17})]),
    ([[2, 'done', ['e1']]], [receipt('e1', 'gmail.show_email', {'email_id': 17})]),
    ([[2, 'done', ['e1']]], [receipt('e1', 'gmail.send_email', {'email_id': 17}, email_addresses=['bob@example.test'])]),
    ([[2, 'done', ['e1']], [2, 'partial', ['e1']]],
     [receipt('e1', 'gmail.send_email', {'email_id': 17}, email_addresses=['alice@example.test'])]),
])
def test_c5_invalid_evidence_preserves_usable_intent_but_never_establishes_completion(evidence, ledger):
    report = inspect_state(packet(evidence, [[2, 'delete']]), PLAN, ledger)
    assert report['mode'] == 'partial'
    assert report['modules']['intent'] and not report['modules']['evidence']
    assert report['state']['plan'][1]['status'] == 'unknown'
    assert report['state']['plan'][1]['evidence_refs'] == []


def test_c5_conflicting_edits_not_applied():
    report = inspect_state(packet([], [[2, 'delete'], ['2', 'keep']]), PLAN, [])
    assert report['mode'] == 'partial' and report['modules']['intent']
    assert not report['modules']['edits'] and report['state']['plan'] == []


def test_g5_uses_visible_original_draft_and_honors_replacement_and_ambiguity():
    intent = {'active': [{'text': 'Attach the file to the reply draft'}],
              'revoked': [{'text': 'Send the draft'}], 'uncertain': []}
    old = [receipt('e1', 'gmail.send_email_from_draft', {}, 'pending', draft_id=12)]
    rule, _ = guard_rule(intent, old, 'Skip the send. Attach the file to the draft.')
    req = {'app': 'gmail', 'api': 'send_email_from_draft', 'arguments': {'draft_id': 12}}
    assert rule is not None and evaluate('call_api', req, rule)[0] == 'block'
    assert evaluate('call_api', {**req, 'arguments': {'draft_id': 13}}, rule)[0] == 'allow'
    assert guard_rule(intent, old, 'Maybe hold off on the send until tomorrow.')[0] is None
    assert guard_rule(intent, old, 'Do not send the draft unless Alice approves.')[0] is None
    intent['active'] = [{'text': 'Skip sending; keep the corrected email as a draft'}]
    assert guard_rule(intent, old, 'Skip the send. Keep it as a draft.')[0] is not None
    assert guard_rule(intent, old, 'Do not send that draft; send a new draft tomorrow.')[0] is None
    intent['active'] = [{'text': 'Send the draft to the replacement recipient'}]
    assert guard_rule(intent, old, 'Do not send the draft to the original recipient.')[0] is None
