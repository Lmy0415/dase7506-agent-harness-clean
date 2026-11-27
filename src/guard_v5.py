"""Pure, fail-open guard. Inputs are limited to the updated visible conversation."""

import re

from src.intent_guard import normal

RULEBOOK = {
    'gmail.send_email': ('mail', ('email_addresses',)),
    'gmail.send_email_from_draft': ('mail', ('draft_id',)),
    'gmail.reply_to_email': ('mail', ('email_thread_id', 'email_id')),
    'gmail.forward_email_from_thread': ('mail', ('thread_id', 'email_addresses')),
    'phone.send_text_message': ('text', ('phone_number',)),
    'venmo.create_payment_request': ('request', ('user_email', 'amount')),
    'venmo.create_transaction': ('pay', ('receiver_email', 'amount')),
    'venmo.deny_payment_request': ('deny', ('payment_request_id',)),
    'amazon.initiate_return': ('return', ('order_id', 'product_id')),
    'supervisor.complete_task': ('answer', ('answer',)),
}
ACTION = {
    'mail': r'\b(?:send(?:ing)?\b(?!\s+.*\b(?:text|request|payment)\b)|emailing|email (?:it|them|him|her)|reply(?:ing)?(?!\s+draft)|forward(?:ing)?)\b',
    'text': r'\b(?:text(?:ing)?(?: message)?|sms)\b',
    'request': r'\b(?:payment request|venmo request|request(?:ing)? (?:money|payment)|request(?:ing)?(?: the)? share)\b',
    'pay': r'\b(?:pay(?:ing)?|payback|reimburs\w+|transfer(?:ring)?|send money)\b',
    'deny': r'\b(?:reject(?:ing)?|deny(?:ing)?|declin(?:e|ing))\b',
    'return': r'\breturn(?:ing)?\b',
    'answer': r'\b(?:answer(?:ing)?|report(?:ing)? (?:the |my )?(?:answer|result)|tell(?:ing)? me)\b',
}
NEGATE = re.compile(r"\b(?:skip|cancel|forget|omit|drop|do not|don't|instead of|rather than|without)\b", re.I)
REPLACE_ALL = re.compile(r'^\s*(?:wait\s*[,—-]\s*)?(?:forget|scratch|cancel) (?:that|the original task)\b', re.I)
READ = {
    'gmail.show_draft', 'gmail.show_drafts', 'gmail.show_email',
    'venmo.show_transactions', 'venmo.show_sent_payment_requests', 'venmo.show_received_payment_requests',
    'venmo.search_users', 'amazon.show_order', 'amazon.show_orders', 'phone.search_contacts',
    'file_system.show_file', 'file_system.show_directory', 'simple_note.show_note',
    'spotify.show_playlist', 'spotify.show_playlist_songs',
}
CLAUSE = re.compile(r'[;—!?]|\.(?=\s|$)|,\s+(?:just|only|but|instead|and then)\b', re.I)


def has_action(kind, text):
    return bool(re.search(ACTION[kind], text, re.I))


def withdrawals(kind, update):
    for match in NEGATE.finditer(update):
        following = CLAUSE.split(update[match.end():], maxsplit=1)[0]
        if has_action(kind, following) and not re.search(r'\b(?:unless|until|except|if)\b', following, re.I):
            return True
    return False


def positive_action(kind, text):
    clauses = re.split(r'[;—.!?]|\b(?:and|but|however)\b', text, flags=re.I)
    return any(has_action(kind, clause) and not withdrawals(kind, clause) for clause in clauses)


def guard_rule(intent, ledger, update):
    """Derive one narrow signature from visible evidence and explicit cancellation."""
    if not intent or not intent['revoked']:
        return None, 'no_valid_revoked_intent'
    pending = next((entry for entry in reversed(ledger) if entry['status'] == 'pending'), None)
    if pending is None or pending['api'] not in RULEBOOK:
        return None, 'unsupported_pending_api'
    if not isinstance(pending['arguments'], dict):
        return None, 'missing_pending_identity'
    api = pending['api']
    kind, keys = RULEBOOK[api]
    revoked = ' '.join(row['text'] for row in intent['revoked'])
    active = ' '.join(row['text'] for row in intent['active'] + intent['uncertain'])
    selection = {key: normal(pending['arguments'].get(key)) for key in keys}
    if api == 'gmail.reply_to_email':
        selection = {key: val for key, val in selection.items() if val is not None}
    if not selection or any(value is None or value == '' or value == () for value in selection.values()):
        return None, 'missing_pending_identity'
    if not has_action(kind, revoked):
        return None, 'revocation_does_not_match_action'

    # Exact amount substitutions may retain the recipient and payment action.
    if kind in ('pay', 'request') and type(selection.get('amount')) in (float, int):
        old = re.escape(format(selection['amount'], 'g'))
        replaced = re.search(r'\b(?:instead of|rather than|not)\s+(?:the\s+)?\$?' + old + r'(?!\d|\.\d)',
                             update, re.I)
        same_active_amount = re.search(r'(?<![\d.])' + old + r'(?!\d|\.\d)', active)
        if replaced and not same_active_amount and re.search(r'(?<![\d.])' + old + r'(?!\d|\.\d)', revoked):
            return {'api': api, 'selector': selection, 'basis': 'explicit_replaced_amount',
                    'evidence_ref': pending['id']}, 'matched'

    if not (withdrawals(kind, update) or REPLACE_ALL.search(update)):
        return None, 'no_explicit_withdrawal'
    if positive_action(kind, active) or positive_action(kind, update):
        return None, 'possibly_active_same_action'
    return {'api': api, 'selector': selection, 'basis': 'explicit_withdrawal',
            'evidence_ref': pending['id']}, 'matched'


def evaluate(tool, request, rule):
    if tool == 'find_api':
        return 'allow', 'documentation'
    if tool != 'call_api' or not isinstance(request, dict):
        return 'unknown', 'unrecognized_tool'
    api = f"{request.get('app')}.{request.get('api')}"
    params = request.get('arguments')
    if not isinstance(params, dict):
        return 'unknown', 'invalid_arguments'
    if api in READ:
        return 'allow', 'documented_read'
    if api == 'supervisor.complete_task' and params.get('answer') in (None, ''):
        return 'allow', 'completion_without_answer'
    if rule is None or api != rule['api']:
        return 'unknown', 'no_matching_rule'
    values = {key: normal(params.get(key)) for key in rule['selector']}
    if any(value is None for value in values.values()):
        return 'unknown', 'missing_identity'
    if values == rule['selector']:
        return 'block', rule['basis']
    return 'allow', 'different_identity_or_amount'
