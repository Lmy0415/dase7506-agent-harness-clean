"""Build aggregate and task-paired results from frozen families and local traces."""

import argparse
import csv
import json
import math
import random
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from src.annotations import ANNOTATIONS
from src.batch import BATCH as PILOT, read
from src.formal import FORMAL, MANIFEST, formal_candidates, ledger_summary
from src.model import ROOT

RESAMPLES, SEED = 10_000, 7506


def to_csv(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(records)


def scheduled_charge(receipt):
    """Apply the verified off-peak rate when the receipt timestamp proves it."""
    amount = receipt['amount_nano_usd']
    if receipt.get('created') is None:
        return amount, False
    issued = datetime.fromtimestamp(receipt['created'], timezone.utc)
    peak_window = issued.weekday() < 5 and (1 <= issued.hour < 4 or 6 <= issued.hour < 10)
    # For a weekday peak window, retain the peak estimate even if a holiday might apply.
    return (amount, False) if peak_window else (amount // 2, True)


def cost_by_run():
    done, reserved, consumed, outstanding = ledger_summary()
    values = defaultdict(Counter)
    for key, reserve in reserved.items():
        stats = values[reserve['purpose']]
        if key in done:
            receipt = done[key]
            usage = receipt['usage']
            scheduled, off_peak = scheduled_charge(receipt)
            stats.update({'calls': 1, 'input_tokens': usage['prompt_tokens'],
                          'output_tokens': usage['completion_tokens'], 'peak_nano_usd': receipt['amount_nano_usd'],
                          'scheduled_nano_usd': scheduled, 'known_offpeak_calls': int(off_peak)})
        else:
            stats['unsettled_or_rejected_calls'] += 1
    return values, {
        'total_peak_nano_usd': consumed, 'outstanding_reservations_nano_usd': outstanding,
        'settled_model_calls': len(done),
        'scheduled_charge_estimate_nano_usd': sum(row['scheduled_nano_usd'] for row in values.values()),
        'known_offpeak_calls': sum(row['known_offpeak_calls'] for row in values.values()),
    }


def events(trace):
    return [item for turn in trace.get('turns', []) for item in turn.get('events', [])]


def request_key(event):
    args, status = event.get('request') or {}, event.get('http_status')
    if not isinstance(args, dict) or not args.get('api') or type(status) is not int or not 200 <= status < 300:
        return None
    return json.dumps(args, sort_keys=True, ensure_ascii=False)


def repeat_counts(prefix, branch):
    seen = {request_key(event) for event in events(prefix)} - {None}
    duplicated = effects = 0
    for event in events(branch):
        key = request_key(event)
        if key is not None:
            if key in seen:
                duplicated += 1
                if event.get('state_before') is not None and event['state_before'] != event['state_after']:
                    effects += 1
            seen.add(key)
    return duplicated, effects


def branch_rows(tasks, costs):
    result = []
    ids, families = set(), set()
    for item in tasks:
        intervention, family = item['intervention_id'], item['family_id']
        if intervention in ids or family in families or set(item['order']) not in ({'A', 'B', 'C'}, {'A', 'B', 'C', 'D'}):
            raise ValueError(f'Invalid or duplicate frozen task {intervention}.')
        ids.add(intervention)
        families.add(family)
        directory = ROOT / item['directory']
        prefix = read(directory / 'prefix.json')
        if prefix.get('context_sha256') != item['context_sha256'] or prefix.get('state') != item['state']:
            raise ValueError(f'Checkpoint changed after freeze for {intervention}.')
        for arm in item['order']:
            path = directory / f'{arm}.json'
            trace = read(path)
            score = trace.get('score')
            if trace and (trace['intervention_id'] != intervention or trace['strategy'] != arm):
                raise ValueError(f'Mismatched branch trace at {path}.')
            if score is not None and arm in 'ABC' and (
                trace['context_sha256'] != prefix['context_sha256'] or trace['state'] != prefix['state']
            ):
                raise ValueError(f'Matched procedures did not share the frozen context at {path}.')
            scores = score or {}
            retained = scores.get('retained_checks', {})
            expected_retained = len(ANNOTATIONS[intervention][1])
            repeats, repeat_effects = repeat_counts(prefix if arm != 'D' else {}, trace)
            usage = costs[f'{directory.name}_{arm}']
            observed = events(trace)
            rejected = sum(type(event.get('http_status')) is int and event['http_status'] >= 400 for event in observed)
            result.append({
                'intervention_id': intervention, 'family_id': family, 'task_id': item['task_id'],
                'type': item['type'], 'stratum': item['stratum'], 'strategy': arm, 'd_subset': int('D' in item['order']),
                'status': 'scored' if score is not None else 'incomplete' if trace else 'missing',
                'stop_reason': trace.get('stop_reason'), 'infrastructure_error': trace.get('infrastructure_error'),
                'revised_final_success': int(scores.get('revised_final_success') is True),
                'official_pass': int(scores.get('official_pass') is True),
                'strict_success': int(scores.get('strict_success') is True) if arm in 'ABC' else None,
                'violation': int(scores['committed_violation']) if scores.get('committed_violation') is not None else None,
                'retained_pass': sum(value is True for value in retained.values()),
                'retained_required': expected_retained,
                'retained_unknown': expected_retained - sum(value is not None for value in retained.values()),
                'revised_assertions_passed': scores.get('revised_passed'), 'revised_assertions_total': scores.get('revised_assertions'),
                'plan_fallback': int(trace.get('fallback') is True), 'rejected_calls': rejected,
                'duplicate_successful_requests': repeats, 'duplicates_changing_monitored_state': repeat_effects,
                'logged_tool_events': len(observed), 'net_model_calls_with_receipts': usage['calls'],
                'input_tokens': usage['input_tokens'], 'output_tokens': usage['output_tokens'],
                'peak_nano_usd': usage['peak_nano_usd'], 'unsettled_or_rejected_model_calls': usage['unsettled_or_rejected_calls'],
                'wall_seconds_last_attempt': trace.get('wall_seconds'),
                'trace': str(path.relative_to(ROOT)) if path.exists() else None,
                'archived_attempts': len(list(directory.glob(f'{arm}.attempt-*.json'))),
            })
    return result


def cohorts(rows):
    for cohort in ('Full', 'D-matched'):
        available = rows if cohort == 'Full' else [row for row in rows if row['d_subset']]
        for kind in ('All', 'Swap', 'Drop'):
            group = available if kind == 'All' else [row for row in available if row['stratum'] == kind]
            if group:
                yield cohort, kind, group


def summaries(rows):
    for cohort, group, population in cohorts(rows):
        for arm in 'ABCD':
            group_rows = [r for r in population if r['strategy'] == arm]
            if not group_rows or (arm == 'D' and cohort == 'Full'):
                continue
            scored = [r for r in group_rows if r['status'] == 'scored']
            determined = [r for r in group_rows if r['violation'] is not None]
            final_determined = [r for r in determined if r['revised_final_success']]
            yield {
                'cohort': cohort, 'stratum': group, 'strategy': arm, 'n': len(group_rows), 'scored': len(scored),
                'final_success': sum(r['revised_final_success'] for r in group_rows),
                'official_pass': sum(r['official_pass'] for r in group_rows),
                'strict_success': sum(r['strict_success'] for r in group_rows) if arm != 'D' else None,
                'violation_n': len(determined) if arm != 'D' else None,
                'violation_unknown': len(group_rows) - len(determined) if arm != 'D' else None,
                'violations': sum(r['violation'] for r in determined) if arm != 'D' else None,
                'misses': sum(r['violation'] for r in final_determined) if arm != 'D' else None,
                'miss_n': len(final_determined) if arm != 'D' else None,
                'retained_pass': sum(r['retained_pass'] for r in group_rows),
                'retained_required': sum(r['retained_required'] for r in group_rows),
                'retained_unknown': sum(r['retained_unknown'] for r in group_rows),
                'input_tokens': sum(r['input_tokens'] for r in group_rows),
                'output_tokens': sum(r['output_tokens'] for r in group_rows),
                'peak_nano_usd': sum(r['peak_nano_usd'] for r in group_rows),
            }


def percentile(ordered, fraction):
    i = (len(ordered) - 1) * fraction
    lo, hi = math.floor(i), math.ceil(i)
    return ordered[lo] * (hi - i) + ordered[hi] * (i - lo) if lo != hi else ordered[lo]


def paired(rows):
    for cohort, group, population in cohorts(rows):
        if cohort != 'Full':
            continue
        by_arm = {arm: {r['family_id']: r for r in population if r['strategy'] == arm} for arm in 'ABC'}
        for first, second in ('CB', 'BA', 'CA'):
            if set(by_arm[first]) != set(by_arm[second]):
                raise ValueError('Paired cohort keys differ across methods.')
            pairs = [(by_arm[first][family], by_arm[second][family]) for family in sorted(by_arm[first])]
            for mode in ('all_manifest', 'both_scored'):
                chosen = pairs if mode == 'all_manifest' else [
                    (a, b) for a, b in pairs if a['status'] == b['status'] == 'scored']
                if not chosen:
                    continue
                cross = Counter((a['strict_success'], b['strict_success']) for a, b in chosen)
                deltas = [a['strict_success'] - b['strict_success'] for a, b in chosen]
                n = len(deltas)
                rng = random.Random(SEED)
                sampled = sorted(sum(rng.choices(deltas, k=n)) * 100 / n for _ in range(RESAMPLES))
                yield {'stratum': group, 'comparison': f'{first}-{second}', 'denominator': mode,
                       'n': n, 'improved': cross[1, 0], 'regressed': cross[0, 1], 'both_pass': cross[1, 1],
                       'both_fail': cross[0, 0], 'difference_pp': sum(deltas) * 100 / n,
                       'lower_95_pp': percentile(sampled, .025), 'upper_95_pp': percentile(sampled, .975)}


def errors(rows):
    counts = Counter()
    for row in rows:
        arm = row['strategy']
        counts[arm, row['infrastructure_error'] or row['stop_reason'] or row['status']] += 1
        if row['plan_fallback']:
            counts[arm, 'planning_fallback'] += 1
        if row['rejected_calls']:
            counts[arm, 'branch_contained_rejected_tool'] += 1
    return [{'strategy': arm, 'outcome': event, 'branches': count}
            for (arm, event), count in sorted(counts.items())]


def screening_rows(tasks):
    screened = read(FORMAL / 'screening.json')
    included = {task['family_id']: task['intervention_id'] for task in tasks}
    for candidate in formal_candidates():
        number = candidate['intervention_id']
        status = screened.get(str(number), {})
        if status:
            decision = status['status']
        elif candidate['family_id'] in included:
            decision = 'another_variant_admitted'
        else:
            decision = 'not_reached_under_screening_rule'
        yield {**candidate, 'decision': decision, 'prefix_calls_last_attempt': status.get('prefix_calls'),
               'prefix_stop': status.get('prefix_stop'),
               'prefix_trace': f"{status['directory']}/prefix.json" if status.get('directory') else None}


def cost_rows(costs, tasks):
    accepted = {Path(item['directory']).name for item in tasks}
    by_stage = defaultdict(Counter)
    for run, measures in costs.items():
        if run.startswith('formal_'):
            case, _, suffix = run.rpartition('_')
            if suffix == 'prefix':
                category = 'formal_prefix_admitted' if case in accepted else 'formal_prefix_not_admitted'
            else:
                category = f'formal_{suffix}'
        elif run.startswith(('pilot_', 'matched_487_')):
            category = 'pilot'
        else:
            category = 'bootstrap_and_diagnostics'
        by_stage[category].update(measures)
    return [{'stage': name, **{k: stats[k] for k in (
        'calls', 'input_tokens', 'output_tokens', 'peak_nano_usd', 'scheduled_nano_usd',
        'known_offpeak_calls', 'unsettled_or_rejected_calls'
    )}} for name, stats in sorted(by_stage.items())]


def pilot_tasks():
    records = read(PILOT / 'progress.json')
    for item in records.values():
        if item['status'] == 'admitted':
            directory = Path(item['directory'])
            prefix = read(directory / 'prefix.json')
            yield {**item, 'order': list('ABCD'), 'context_sha256': prefix['context_sha256'], 'state': prefix['state']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pilot', action='store_true')
    args = parser.parse_args()
    tasks = list(pilot_tasks()) if args.pilot else read(MANIFEST).get('tasks')
    if not tasks:
        raise RuntimeError('A verified pilot or a frozen formal manifest is required.')
    target = ROOT / 'results' / 'pilot' if args.pilot else ROOT / 'results'
    costs, budget = cost_by_run()
    rows = branch_rows(tasks, costs)
    to_csv(target / 'branch_metrics.csv', rows)
    to_csv(target / 'summary.csv', list(summaries(rows)))
    to_csv(target / 'paired.csv', list(paired(rows)))
    to_csv(target / 'errors.csv', errors(rows))
    (target / 'budget.json').write_text(json.dumps(budget, indent=2) + '\n')
    if not args.pilot:
        to_csv(target / 'screening_cases.csv', list(screening_rows(tasks)))
        to_csv(target / 'cost_breakdown.csv', cost_rows(costs, tasks))
    print(json.dumps({'result_directory': str(target), 'cases': len(tasks),
                      'branch_count': len(rows), 'scored': sum(row['status'] == 'scored' for row in rows)}))


if __name__ == '__main__':
    main()
