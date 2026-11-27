"""DeepSeek Chat Completions with a shared local budget ledger."""

import fcntl
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from time import CLOCK_REALTIME, clock_gettime
from uuid import uuid4

import requests
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / 'artifacts' / 'raw' / 'api_costs.jsonl'
MODEL = 'deepseek-flash'
URL = 'https://api.deepseek.com/chat/completions'
NANO_USD_PER_DOLLAR = 1_000_000_000
BUDGET = 10 * NANO_USD_PER_DOLLAR
# Integer nano-USD per token, at peak rates. Reserve the entire advertised context.
INPUT_CACHE_HIT, INPUT_CACHE_MISS, OUTPUT = 6, 300, 1200
CONTEXT_LIMIT = 1_048_576


class BudgetLimit(RuntimeError):
    pass


class TransientModelError(RuntimeError):
    pass


@contextmanager
def locked_ledger():
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open('a+', encoding='utf-8') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        handle.seek(0)
        yield handle


def append_event(handle, **event):
    handle.seek(0, os.SEEK_END)
    # The simulator freezes datetime.now(), but the ledger needs the host's wall clock.
    utc = datetime.fromtimestamp(clock_gettime(CLOCK_REALTIME), timezone.utc).isoformat()
    handle.write(json.dumps({'utc': utc, **event}) + '\n')
    handle.flush()
    os.fsync(handle.fileno())


def reserve(request_id, purpose, max_tokens):
    amount = CONTEXT_LIMIT * INPUT_CACHE_MISS + max_tokens * OUTPUT
    with locked_ledger() as handle:
        latest_amounts = {}
        for event in map(json.loads, handle):
            if 'amount_nano_usd' in event:
                latest_amounts[event['request_id']] = event['amount_nano_usd']
        if sum(latest_amounts.values()) + amount > BUDGET:
            raise BudgetLimit('Project budget cannot cover another request reservation.')
        append_event(handle, request_id=request_id, purpose=purpose, status='reserved', amount_nano_usd=amount)


def record(request_id, status, **fields):
    with locked_ledger() as handle:
        append_event(handle, request_id=request_id, status=status, **fields)


def complete(messages, *, purpose, max_tokens=512, tools=None, tool_choice=None, json_output=False):
    if not 1 <= max_tokens <= 1024:
        raise ValueError('max_tokens must be between 1 and 1024 for this experiment.')
    api_key = os.environ.get('DEEPSEEK_API_KEY') or dotenv_values(
        ROOT / '.env', interpolate=False
    ).get('DEEPSEEK_API_KEY')
    if not api_key or not api_key.strip():
        raise RuntimeError('Set DEEPSEEK_API_KEY in the project .env or environment.')
    payload = {
        'model': MODEL,
        'messages': messages,
        'thinking': {'type': 'disabled'},
        'max_tokens': max_tokens,
    }
    if tools:
        payload['tools'] = tools
    if tool_choice is not None:
        payload['tool_choice'] = tool_choice
    if json_output:
        payload['response_format'] = {'type': 'json_object'}

    request_id = uuid4().hex
    reserve(request_id, purpose, max_tokens)
    try:
        response = requests.post(
            URL, json=payload, headers={'Authorization': f'Bearer {api_key.strip()}'},
            allow_redirects=False, timeout=(10, 120),
        )
    except requests.RequestException as error:
        record(request_id, 'unconfirmed_transport', error_type=type(error).__name__)
        raise TransientModelError('DeepSeek request did not return a response. Its reservation remains.') from None
    if response.status_code != 200:
        if response.status_code in {400, 401, 402, 404, 422, 429}:
            record(request_id, 'rejected', http_status=response.status_code, amount_nano_usd=0)
        else:
            record(request_id, 'unconfirmed_http_status', http_status=response.status_code)
        error = TransientModelError if response.status_code in {408, 429} or response.status_code >= 500 else RuntimeError
        raise error(f'DeepSeek rejected the request or failed with HTTP {response.status_code}.')

    data = response.json()
    usage = data['usage']
    prompt_tokens = usage['prompt_tokens']
    output_tokens = usage['completion_tokens']
    cache_hits = usage.get('prompt_cache_hit_tokens', 0)
    if not 0 <= cache_hits <= prompt_tokens <= CONTEXT_LIMIT or not 0 <= output_tokens <= max_tokens:
        raise RuntimeError('DeepSeek usage exceeded the expected bounds. The reservation remains.')
    amount = cache_hits * INPUT_CACHE_HIT + (prompt_tokens - cache_hits) * INPUT_CACHE_MISS + output_tokens * OUTPUT
    record(
        request_id, 'settled_peak_price', amount_nano_usd=amount, usage=usage,
        model=data.get('model'), response_id=data.get('id'), created=data.get('created'),
        system_fingerprint=data.get('system_fingerprint'),
    )
    return data
