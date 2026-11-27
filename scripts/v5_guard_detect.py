"""Standalone predictor. It accepts one feature file and cannot import the scorer."""

import argparse
import hashlib
import json
from pathlib import Path

from src.guard_v5 import evaluate, guard_rule
from src.intent_guard import decision, supported_signature
from src.intent_revision import visible_receipts

FIELDS = {'record_id', 'original', 'update', 'prior_history', 'interruption_history',
          'v4_intent', 'c5_intent', 'tool', 'request'}


def predict(record):
    if set(record) != FIELDS:
        raise ValueError('Unexpected feature fields.')
    if record['prior_history'][:len(record['interruption_history'])] != record['interruption_history']:
        raise ValueError('The interruption history must precede the candidate call.')
    ledger = visible_receipts(record['interruption_history'])
    previous = {'execution': ledger, 'intent': record['v4_intent']} if record['v4_intent'] else None
    v4 = supported_signature(previous, record['update'])
    v5, readiness = guard_rule(record['c5_intent'], ledger, record['update'])
    value, reason = evaluate(record['tool'], record['request'], v5)
    return {'record_id': record['record_id'],
            'v4': {'decision': decision(record['tool'], record['request'], v4), 'has_rule': v4 is not None},
            'v5': {'decision': value, 'has_rule': v5 is not None, 'readiness': readiness, 'reason': reason}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('features', type=Path)
    parser.add_argument('predictions', type=Path)
    args = parser.parse_args()
    payload = args.features.read_bytes()
    values = [predict(json.loads(line)) for line in payload.splitlines()]
    args.predictions.write_text(''.join(json.dumps(row) + '\n' for row in values))
    print(len(values), 'predictions; input SHA-256', hashlib.sha256(payload).hexdigest())


if __name__ == '__main__':
    main()
