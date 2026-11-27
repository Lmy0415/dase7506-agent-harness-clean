"""Audit retained requirements in the six formal partial drops using saved scores."""

import csv
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# These selectors identify existing benchmark checks. This audit runs after the
# experiment and does not modify the frozen score or any branch outcome.
CASES = {
    247: [
        ('target_alarm', 'exactly one alarm was updated and its id'),
        ('new_time', 'updated time on the target alarm matches'),
    ],
    244: [
        ('payment_recipient', "added transaction's receiver_id"),
        ('payment_note', 'added transaction has description'),
        ('payment_amount', 'added transaction has amount'),
    ],
    263: [('retained_likes', 'Likes are exactly the received-coworker-this-year transactions.')],
    772: [('slide_paths_and_content', '.ppt files were renamed to their target paths')],
    763: [('corrected_payment', None)],
    783: [('food_share_payment', 'exactly 1 venmo.Transaction added to Nancy')],
}


def main():
    manifest = json.loads((ROOT / 'protocol/formal_manifest.json').read_text())
    tasks = [row for row in manifest['tasks'] if row['stratum'] == 'Drop']
    if {row['intervention_id'] for row in tasks} != set(CASES):
        raise ValueError('Retention audit covers the six frozen partial-drop cases.')
    rows = []
    for task in tasks:
        number = task['intervention_id']
        for arm in task['order']:
            trace = json.loads((ROOT / task['directory'] / f'{arm}.json').read_text())
            score = trace['score']
            passed = score['revised_passed_requirements']
            failed = [failure['requirement'] for failure in score['revised_failures']]
            for label, selector in CASES[number]:
                matches = [] if selector is None else [
                    status for status, requirements in [('pass', passed), ('fail', failed)]
                    for clause in requirements if selector.lower() in clause.lower()
                ]
                result = matches[0] if len(matches) == 1 else 'unknown'
                rows.append({'intervention_id': number, 'strategy': arm, 'retained_condition': label,
                             'result': result, 'basis': 'shared_benchmark_assertion' if selector else 'evaluator_mismatch'})
    out = ROOT / 'results' / 'retention_audit.csv'
    with out.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)
    for arm in 'ABCD':
        print(arm, dict(Counter(row['result'] for row in rows if row['strategy'] == arm)))


if __name__ == '__main__':
    main()
