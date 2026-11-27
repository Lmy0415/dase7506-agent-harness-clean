import json
from unittest.mock import patch

import pytest

from src.env_adapter import Simulator
from src.harness_v4 import GuardedSimulator
from src.intent_guard import decision, supported_signature
from src.intent_revision import intent_state, revised_goal, visible_receipts


def receipt(app, api, arguments, body, http=200):
    return [
        {'role': 'assistant', 'tool_calls': [{'id': 'call', 'function': {
            'name': 'call_api', 'arguments': json.dumps({'app': app, 'api': api, 'arguments': arguments}),
        }}]},
        {'role': 'tool', 'tool_call_id': 'call', 'content': json.dumps({'http_status': http, 'response': body})},
    ]


def test_consolidation_and_sparse_edit_validation():
    assert revised_goal('{"goal":"Send the requested note to Charlie."}').startswith('Send')
    with pytest.raises(ValueError):
        revised_goal('{"goal":"first","goal":"second"}')
    old = [{'id': 1, 'text': 'Send the note to Alice'}, {'id': 2, 'text': 'Send it to Bob'}]
    history = receipt('gmail', 'send_email', {'email_addresses': ['alice@example.test']},
                      {'message': 'Email sent.', 'email_id': 19})
    value = {'active': [['o', 'Send it to Alice'], ['u', 'Send it to Charlie']], 'revoked': ['Bob'],
             'uncertain': [], 'evidence': [[1, 'done', ['e1']]],
             'edits': [[2, 'replace', ['Send to Charlie']]]}
    state = intent_state(json.dumps(value), old, visible_receipts(history))
    assert [(s['id'], s['status']) for s in state['plan']] == [(1, 'done'), (2, 'cancelled'), ('2.1', 'pending')]
    value['evidence'][0][2] = ['e99']
    with pytest.raises(ValueError, match='reference'):
        intent_state(json.dumps(value), old, visible_receipts(history))
    value['evidence'] = []
    value['edits'] *= 2
    with pytest.raises(ValueError, match='unique'):
        intent_state(json.dumps(value), old, visible_receipts(history))


def test_draft_and_pending_are_not_sent_evidence():
    old = [{'id': 1, 'text': 'Send the email'}]
    value = {'active': [['o', 'Send']], 'revoked': [], 'uncertain': [],
             'evidence': [[1, 'done', ['e1']]], 'edits': []}
    draft = receipt('gmail', 'create_draft', {}, {'draft_id': 1})
    pending = receipt('gmail', 'send_email_from_draft', {'draft_id': 1}, {'status': 'pending'}, http=None)
    for history in (draft, pending):
        with pytest.raises(ValueError):
            intent_state(json.dumps(value), old, visible_receipts(history))


def check_request(app, api, **args):
    return {'app': app, 'api': api, 'arguments': args}


def test_guard_is_precise_and_does_not_invoke_simulator_on_block():
    bob = 'bob@example.test'
    alice = 'alice@example.test'
    msg = 'Do not send the email to bob@example.test. Send to alice@example.test instead.'
    state = {'intent': {'active': [{'text': 'Send it to alice@example.test'}], 'uncertain': [],
                        'revoked': [{'text': 'Send the email to bob@example.test'}]},
             'execution': visible_receipts(receipt(
                 'gmail', 'send_email', {'email_addresses': [bob]}, {'status': 'pending'}, http=None))}
    signature = supported_signature(state, msg)
    assert signature is not None
    request = check_request('gmail', 'send_email', email_addresses=[bob])
    assert decision('call_api', request, signature) == 'block'
    assert decision('call_api', check_request('gmail', 'send_email', email_addresses=[alice]), signature) == 'allow'
    assert decision('call_api', check_request('gmail', 'show_drafts'), signature) == 'allow'
    assert decision('call_api', check_request('gmail', 'send_email'), signature) == 'unknown'
    assert decision('call_api', check_request('gmail', 'create_draft'), signature) == 'unknown'
    state['intent']['active'].append({'text': 'Send a new version to bob@example.test'})
    assert supported_signature(state, msg) is None
    simulator = GuardedSimulator.__new__(GuardedSimulator)
    simulator.signature, simulator.decisions = signature, []
    with patch.object(Simulator, 'invoke') as invoke:
        event = simulator.invoke('call_api', request)
        invoke.assert_not_called()
    assert event['response']['blocked'] and not simulator.decisions[0]['submitted']


def test_guard_distinguishes_the_replacement_payment_amount():
    email = 'alice@example.test'
    state = {'intent': {'active': [{'text': f'Pay {email} $30'}], 'uncertain': [],
                        'revoked': [{'text': f'Pay {email} $20'}]},
             'execution': visible_receipts(receipt(
                 'venmo', 'create_transaction', {'receiver_email': email, 'amount': 20},
                 {'status': 'pending'}, http=None))}
    signature = supported_signature(state, f'Pay {email} $30 instead of $20.')
    assert signature is not None
    for amount, expected in [(20, 'block'), (30, 'allow')]:
        request = check_request('venmo', 'create_transaction', receiver_email=email, amount=amount)
        assert decision('call_api', request, signature) == expected
