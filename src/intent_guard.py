"""A conservative execution check using user text and visible request evidence."""

import re


# These are generic documented write APIs. Other API semantics are unclassified.
SELECTORS = {
    'gmail.send_email': ('email_addresses',),
    'gmail.send_email_from_draft': ('draft_id',),
    'gmail.reply_to_email': ('email_thread_id', 'email_id'),
    'phone.send_text_message': ('phone_number',),
    'venmo.create_payment_request': ('user_email', 'amount'),
    'venmo.create_transaction': ('receiver_email', 'amount'),
}
SEND_WITHDRAWN = re.compile(
    r"\b(?:skip the (?:send|email)|(?:do not|don't) (?:send|reply)|without sending)\b", re.I,
)
SEND_WANTED = re.compile(r'\b(?:send|reply|forward|deliver|email (?:to|the))\b', re.I)
WRITE_WORD = re.compile(r'\b(?:send|reply|email|payment|pay|request|transfer|text)\b', re.I)
READ_PREFIXES = ('show_', 'search_', 'list_', 'get_', 'file_exists', 'directory_exists')


def normal(value):
    if isinstance(value, str):
        return value.strip().lower()
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return tuple(sorted(normal(item) for item in value))
    if type(value) in (int, float):
        return value
    return None


def supported_signature(state, update):
    if state is None or not state['intent']['revoked']:
        return None
    pending = next((item for item in reversed(state['execution']) if item['status'] == 'pending'), None)
    if pending is None or pending['api'] not in SELECTORS or not isinstance(pending['arguments'], dict):
        return None
    intent = state['intent']
    still_possible = ' '.join(item['text'] for item in intent['active'] + intent['uncertain']).lower()
    revoked_text = ' '.join(item['text'] for item in intent['revoked']).lower()
    api, original = pending['api'], pending['arguments']
    if not WRITE_WORD.search(revoked_text):
        return None
    selector = {key: normal(original.get(key)) for key in SELECTORS[api]}
    if any(value is None or value == '' or value == () for value in selector.values()):
        return None
    explicit = SEND_WITHDRAWN.search(update)
    if api.startswith('gmail.') and explicit and not SEND_WANTED.search(update[explicit.end():]):
        supported = not SEND_WANTED.search(still_possible)
        reason = 'explicit withdrawal of the pending send or reply'
    elif api in ('gmail.send_email', 'phone.send_text_message'):
        targets = next(iter(selector.values()))
        targets = targets if isinstance(targets, tuple) else (targets,)
        literal = len(targets) == 1 and targets[0] in update.lower() and targets[0] in revoked_text
        supported = literal and targets[0] not in still_possible and bool(explicit)
        reason = 'explicitly withdrawn named destination in pending request'
    elif api.startswith('venmo.'):
        email, amount = selector.values()
        amount_pattern = r'(?<![\d.])' + re.escape(format(amount, 'g')) + r'(?!\d|\.\d)'
        withdrawal = re.search(r"\b(?:instead of|rather than|don't pay|do not pay|skip|not)\b", update, re.I)
        supported = bool(
            withdrawal and email in update.lower() and email in revoked_text
            and re.search(amount_pattern, update[withdrawal.start():])
            and re.search(amount_pattern, revoked_text)
            and not re.search(amount_pattern, still_possible)
        )
        reason = 'explicitly withdrawn destination and amount in pending request'
    else:
        supported = False
        reason = ''
    if not supported:
        return None
    return {'api': api, 'selector': selector, 'source': 'latest_user_update',
            'evidence_ref': pending['id'], 'reason': reason}


def decision(name, request, signature):
    if name == 'find_api':
        return 'allow'
    if name != 'call_api' or not isinstance(request, dict):
        return 'unknown'
    api, app, params = request.get('api'), request.get('app'), request.get('arguments')
    if not isinstance(api, str) or not isinstance(app, str) or not isinstance(params, dict):
        return 'unknown'
    if api.startswith(READ_PREFIXES):
        return 'allow'
    if signature is None or f'{app}.{api}' != signature['api']:
        return 'unknown'
    actual = {key: normal(params.get(key)) for key in signature['selector']}
    if any(value is None for value in actual.values()):
        return 'unknown'
    return 'block' if actual == signature['selector'] else 'allow'
