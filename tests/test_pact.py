import json

from src.pact import Controller, communication, parse_assessment
from src.pact_cases import replace_receipt
from src.pact_runner import occupation

NOTE_DOC = {'parameters': [{'name': 'title'}, {'name': 'content'}]}
CATALOGUE = {'simple_note': {'create_note': NOTE_DOC, 'delete_note': {'parameters': [{'name': 'note_id'}]}}}
UPDATE = 'Create a note titled Urgent Review with fixed content. It is the highest priority.'
RECEIPT = {'id': 'e2', 'api': 'simple_note.create_note', 'arguments': {'title': 'Old Note', 'content': 'old'}}


def card(priority=0, deps=(), endpoint='simple_note.create_note'):
    return {'title': 'Urgent Review', 'endpoint': endpoint, 'selector': {'title': 'Urgent Review'},
            'quote': 'Create a note titled Urgent Review', 'deps': list(deps), 'priority': priority, 'state': 'READY'}


def controller(committed=False, cards=None, fix=''):
    return Controller({'old': 'cancel', 'fix': fix, 'cards': cards or {}},
                      RECEIPT, committed, {'note_id': 32} if committed else {}, CATALOGUE)


def test_replaces_only_matched_pending_receipt():
    request = {'app': 'simple_note', 'api': 'create_note', 'arguments': RECEIPT['arguments']}
    history = [
        {'role': 'assistant', 'tool_calls': [
            {'id': 'wrong', 'function': {'name': 'call_api', 'arguments': '{malformed'}}]},
        {'role': 'assistant', 'tool_calls': [
            {'id': 'right', 'function': {'name': 'call_api', 'arguments': json.dumps(request)}}]},
        {'role': 'tool', 'tool_call_id': 'right',
         'content': json.dumps({'http_status': None, 'response': {'status': 'pending', 'committed': False}})},
    ]
    after = replace_receipt(history, {'arguments': request, 'committed': False},
                            {'http_status': 200, 'response': {'note_id': 32}})
    assert after[:-1] == history[:-1]
    assert json.loads(after[-1]['content']) == {'http_status': 200, 'response': {'note_id': 32}, 'committed': True}


def test_partial_assessment_never_invents_dependencies():
    raw = {'old': 'cancel', 'basis': 'not in the user request', 'fix': '',
           'tasks': [['title', 'simple_note.create_note', {'title': 'Urgent Review'},
                      'Create a note titled Urgent Review', ['0', 0], '1']]}
    x = parse_assessment(json.dumps(raw), UPDATE, 'original request', CATALOGUE)
    assert x['old'] == 'unknown' and x['cards'][1]['deps'] == [0]


def test_cycle_blocks_card_without_blocking_independent_card():
    raw = {'old': 'unknown', 'basis': '', 'fix': '', 'tasks': [
        ['title', 'simple_note.create_note', {}, 'Create a note titled Urgent Review', [1], 0],
        ['title', 'simple_note.create_note', {}, 'Create a note titled Urgent Review', [], 0]]}
    x = parse_assessment(json.dumps(raw), UPDATE, '', CATALOGUE)
    assert x['cards'][1]['state'] == 'BLOCKED' and x['cards'][2]['state'] == 'READY'


def test_cancel_and_wait_use_different_communications():
    assert controller(False).messages_to_user() == []
    events = controller(True).messages_to_user()
    assert [e['tool'] for e in events] == ['report_conflict', 'request_decision']
    assert events[1]['response']['authorization'] == 'no_reply_pending'
    assert all(not row['submitted'] for row in events)


def test_explicit_repair_requires_exact_object():
    x = controller(True, fix='I authorize you to delete this note.')
    req = {'app': 'simple_note', 'api': 'delete_note', 'arguments': {'note_id': 31}}
    assert not x.gate(req, UPDATE, [])[0]
    req['arguments']['note_id'] = 32
    assert x.gate(req, UPDATE, [])[:2] == (True, 'exact_authorized_inverse')
    assert controller(True, fix='I authorize you: do not delete this note.').repair is None


def test_priority_dependency_and_approval():
    x = controller(cards={1: card(0), 2: card(1, [1]), 3: card(1, [0]), 4: card(2)})
    assert x.selected() == 1
    x.after(1, {'http_status': 200, 'response': {'note_id': 12}}, 'simple_note.create_note')
    assert x.selected() == 2
    x.after(2, {'http_status': 200, 'response': {'note_id': 13}}, 'simple_note.create_note')
    assert x.selected() == 4


def test_blank_200_is_not_semantic_completion():
    x = controller(cards={1: card()})
    x.after(1, {'http_status': 200, 'response': {'message': 'Unrelated effect.'}}, 'simple_note.create_note')
    assert x.selected() == 1


def test_communication_does_not_invent_user_approval():
    event = communication('request_decision', {'receipt': 'e1', 'question': 'Proceed?',
                         'paused_task': 'old operation', 'options': ['Wait', 'Proceed later']})
    assert event['http_status'] == 200 and not event['complete'] and not event['submitted']


def test_budget_counts_unreturned_request_in_both_scopes():
    rows = [{'request_id': 'older', 'status': 'reserved', 'purpose': 'v5_x', 'amount_nano_usd': 120},
            {'request_id': 'new', 'status': 'reserved', 'purpose': 'pact_x', 'amount_nano_usd': 25},
            {'request_id': 'older', 'status': 'settled_peak_price', 'amount_nano_usd': 15},
            {'request_id': 'new', 'status': 'unconfirmed_transport'}]
    assert occupation(rows) == (40, 25, 25)
