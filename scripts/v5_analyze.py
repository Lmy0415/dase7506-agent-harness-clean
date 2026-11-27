"""Rebuild V5 descriptive and paired results from frozen local traces."""

import csv
import math
import random
from collections import Counter

from src import harness_v4, harness_v5, v5_sampling
from src.analyze import cost_by_run, events, percentile, to_csv
from src.batch import read
from src.expansion import sha
from src.runner import write_json

ROOT, RAW, RESULTS = harness_v5.ROOT, harness_v5.RAW, harness_v5.RESULTS
MEASURES = ('calls', 'input_tokens', 'output_tokens', 'peak_nano_usd', 'scheduled_nano_usd')
COMPARISONS = (('C5', 'C+'), ('C5', 'C'), ('C5', 'A'), ('G5', 'C5'))


def audited_blocks(trace, prefix):
    executed = False
    counts = Counter()
    probe = prefix.get('boundary_probe', {})
    for e in events(trace):
        response = e.get('response')
        if isinstance(response, dict) and response.get('blocked') is True:
            if not executed and e['request'] == probe.get('request') and 200 <= probe.get('http_status', 0) < 300:
                counts['confirmed_conflict' if probe.get('forbidden_transitions') else 'confirmed_nonconflict'] += 1
            else:
                counts['unverified_block'] += 1
        elif 'state_before' in e:
            executed = True
    return counts


def branch(item, arm, phase, cohort, costs, historical=False):
    n = item['intervention_id']
    base = ROOT / item['directory']
    if historical:
        folder = harness_v4.RAW / 'v4_formal' / f'case_{n}' if arm in ('R', 'C+', 'C++') else base
    else:
        folder = RAW / phase / f'case_{n}' if arm in ('C5', 'G5') else base
    path = folder / f'{arm}.json'
    trace = read(path)
    if trace and (trace['intervention_id'] != n or trace['strategy'] != arm):
        raise RuntimeError(f'Trace mismatch at {path}.')
    known = trace.get('score') is not None
    if known and arm != 'D' and any(trace.get(k) != item[k] for k in ('context_sha256', 'state')):
        raise RuntimeError(f'Checkpoint does not match at {path}.')
    score = trace.get('score') or {}
    visible_events = events(trace)
    flagged = [x for x in visible_events if x.get('forbidden_transitions')]
    kind = {e['request'].get('app') for e in flagged}
    mode = trace.get('state_mode')
    if arm in ('C+', 'C++') and known:
        mode = 'fallback' if trace.get('fallback') else 'full'
    guard = trace.get('guard', {})
    checks = guard.get('checks', trace.get('guard_decisions', []))
    counts = Counter(r['decision'] for r in checks)
    guarded_api = (guard.get('rule') or trace.get('guard_signature') or {}).get('api')
    same_endpoint = sum(
        bool(guarded_api) and f"{x['request'].get('app')}.{x['request'].get('api')}" == guarded_api
        for x in checks if isinstance(x.get('request'), dict)
    )
    audit = audited_blocks(trace, read(base / 'prefix.json'))
    assert sum(audit.values()) == counts['block']
    own = costs.get(trace.get('run_id'), {})
    shared = costs.get(trace.get('shared_revision_id'), {})
    revision = read(folder / 'revision.json') if arm in ('C5', 'G5') else {}
    accepted = trace.get('components', {})
    retained = score.get('retained_checks', {})
    result = {
        'intervention_id': n, 'family_id': item['family_id'], 'task_id': item['task_id'],
        'cohort': cohort, 'stratum': item['stratum'], 'arm': arm,
        'status': 'scored' if known else 'incomplete' if trace else 'missing',
        'stop_reason': trace.get('stop_reason'), 'infrastructure_error': trace.get('infrastructure_error'),
        'final': int(bool(score.get('revised_final_success'))),
        'official': int(bool(score.get('official_pass'))),
        'strict': int(bool(score.get('strict_success'))) if arm != 'D' else None,
        'violation': int(bool(flagged)) if known and arm != 'D' else None,
        'supervisor_violation': int('supervisor' in kind) if known and arm != 'D' else None,
        'application_violation': int(bool(kind - {'supervisor', None})) if known and arm != 'D' else None,
        'supervisor_violation_events': sum(e['request'].get('app') == 'supervisor' for e in flagged) if arm != 'D' else None,
        'application_violation_events': sum(e['request'].get('app') not in (None, 'supervisor')
                                            for e in flagged) if arm != 'D' else None,
        'retention_n': len(retained), 'retention_known': sum(v is not None for v in retained.values()),
        'retention_satisfied': sum(v is True for v in retained.values()),
        'state_mode': mode, 'state_repair': int(len(revision.get('turns', [])) == 2) if revision else None,
        'format_errors': sum('plan_parse_error' in t for t in trace.get('turns', [])) if not revision else sum(
            any(e.startswith(('JSON envelope', 'intent:', 'edits:')) for e in t.get('component_report', {}).get('issues', []))
            for t in revision['turns']),
        'evidence_downgraded_steps': len(accepted.get('downgraded_steps', [])),
        'component_issues': len(accepted.get('issues', [])),
        'guard_rules': int(bool(guard.get('rule') or trace.get('guard_signature'))),
        'guard_readiness': guard.get('readiness'), 'guard_allow': counts['allow'], 'guard_block': counts['block'],
        'guard_unknown': counts['unknown'], 'guard_checked': len(checks), 'guard_submitted': sum(bool(c.get('submitted')) for c in checks),
        'guard_same_endpoint_proposals': same_endpoint,
        'guard_confirmed_conflict': audit['confirmed_conflict'],
        'guard_confirmed_nonconflict': audit['confirmed_nonconflict'],
        'guard_unverified_block': audit['unverified_block'],
        'guard_recovered': int(bool(guard.get('recovered_after_block'))),
        'guard_model_calls': guard.get('model_calls', 0),
        'tool_calls': len(visible_events),
        'execution_calls_final_attempt': len(trace.get('turns', [])),
        'logical_calls_final_attempt': len(trace.get('turns', [])) + trace.get('shared_calls', 0),
        'wall_seconds': trace.get('wall_seconds'), 'shared_wall_seconds': revision.get('wall_seconds'),
        'trace': str(path.relative_to(ROOT)) if trace else None,
    }
    for metric in MEASURES:
        result[metric] = own.get(metric, 0)
        result[f'shared_{metric}'] = shared.get(metric, 0)
        result[f'logical_{metric}'] = result[metric] + result[f'shared_{metric}']
    return result


def split(rows):
    for cohort in sorted({r['cohort'] for r in rows}):
        for stratum in ('all', 'Swap', 'Drop'):
            selected = [r for r in rows if r['cohort'] == cohort and (stratum == 'all' or r['stratum'] == stratum)]
            if selected:
                yield cohort, stratum, selected


def summary(rows):
    for cohort, stratum, selected in split(rows):
        for arm in dict.fromkeys(row['arm'] for row in selected):
            group = [r for r in selected if r['arm'] == arm]
            violations = [r for r in group if r['violation'] is not None]
            final_known = [r for r in violations if r['final']]
            success_key = 'final' if arm == 'D' else 'strict'
            success = [r for r in group if r[success_key]]
            states = Counter(r['state_mode'] for r in group)
            reach = {key: sum(r[key] or 0 for r in group) for key in (
                'strict', 'final', 'official', 'violation', 'supervisor_violation', 'application_violation',
                'supervisor_violation_events', 'application_violation_events',
                'retention_n', 'retention_known', 'retention_satisfied',
                'format_errors', 'evidence_downgraded_steps', 'component_issues', 'state_repair',
                'tool_calls', 'guard_rules', 'guard_allow', 'guard_block', 'guard_unknown', 'guard_checked',
                'guard_submitted', 'guard_same_endpoint_proposals', 'guard_confirmed_conflict', 'guard_confirmed_nonconflict',
                'guard_unverified_block', 'guard_recovered', 'guard_model_calls',
                *MEASURES, *(f'shared_{m}' for m in MEASURES), *(f'logical_{m}' for m in MEASURES),
            )}
            yield {
                'cohort': cohort, 'stratum': stratum, 'arm': arm, 'n': len(group),
                'scored': sum(r['status'] == 'scored' for r in group),
                'missing_or_incomplete': sum(r['status'] != 'scored' for r in group),
                'full': states['full'], 'partial': states['partial'], 'fallback': states['fallback'],
                'limit': sum(r['stop_reason'] == 'model_call_limit' for r in group),
                'known_violation_n': len(violations), 'miss_n': len(final_known),
                'missed_violation': sum(r['violation'] for r in final_known),
                'successful_n': len(success), 'success_logical_peak_nano_usd': sum(r['logical_peak_nano_usd'] for r in success),
                **reach,
            }


def pairs(rows):
    for cohort, stratum, group in split(rows):
        if cohort == 'pilot':
            continue
        lookup = {(r['arm'], r['family_id']): r for r in group}
        families = sorted({r['family_id'] for r in group})
        for a, b in COMPARISONS:
            present = {r['arm'] for r in group}
            if not {a, b} <= present:
                continue
            n = len(families)
            pair = Counter((lookup[a, f]['strict'], lookup[b, f]['strict']) for f in families)
            differences = [lookup[a, f]['strict'] - lookup[b, f]['strict'] for f in families]
            rng = random.Random(7506)
            samples = sorted(100 * sum(rng.choices(differences, k=n)) / n for _ in range(10000))
            up, down = pair[1, 0], pair[0, 1]
            p = min(1, 2 * sum(math.comb(up + down, k) for k in range(min(up, down) + 1)) / 2**(up + down))
            yield {'cohort': cohort, 'stratum': stratum, 'first': a, 'second': b, 'n': n,
                   'first_only': up, 'second_only': down, 'both': pair[1, 1], 'neither': pair[0, 0],
                   'net': up - down, 'delta_pp': (up - down) * 100 / n,
                   'low_95': percentile(samples, .025), 'high_95': percentile(samples, .975),
                   'exact_mcnemar_unadjusted': p, 'denominator': 'all_manifest'}


def sensitivity(rows):
    change_path = RESULTS / 'evaluator_audit.csv'
    audited = {(int(r['intervention_id']), r['strategy']): r for r in csv.DictReader(change_path.open())
               if r['rescore'] == 'done'}
    for arm in dict.fromkeys(r['arm'] for r in rows if r['cohort'] == 'historical_40'):
        group = [r for r in rows if r['cohort'] == 'historical_40' and r['arm'] == arm]
        recorded = 'final' if arm == 'D' else 'strict'
        deltas = []
        for current in group:
            edited = audited.get((current['intervention_id'], arm))
            if edited:
                deltas.append(int(edited[f'audited_{recorded}'] == 'True') - current[recorded])
        original = sum(r[recorded] for r in group)
        yield {'arm': arm, 'n': len(group), 'metric': recorded, 'original': original,
               'audited_cases': len(deltas), 'revised': original + sum(deltas),
               'gains': deltas.count(1), 'losses': deltas.count(-1)}


def main():
    plan = read(harness_v5.MANIFEST)
    assert plan['settings_sha256'] == sha(harness_v5.SETTINGS)
    costs, budget = cost_by_run()
    rows = []
    for i in plan['tasks']:
        for arm in ('A', 'B', 'C', 'R', 'C+', 'C++', 'D'):
            rows.append(branch(i, arm, 'v5_formal', 'historical_40', costs, historical=True))
        for arm in i['v5_order']:
            rows.append(branch(i, arm, 'v5_formal', 'historical_40', costs))
    for i in read(harness_v5.RAW / 'pilot_settings.json')['cases']:
        for arm in i['v5_order']:
            rows.append(branch(i, arm, 'v5_pilot', 'pilot', costs))
    holdout = read(v5_sampling.MANIFEST)
    if holdout:
        assert holdout['selection_sha256'] == sha(v5_sampling.SETTINGS)
        assert not {i['family_id'] for i in holdout['tasks']} & {i['family_id'] for i in plan['tasks']}
    for i in holdout.get('tasks', []):
        for arm in [*i['order'], *i['v5_order']]:
            rows.append(branch(i, arm, 'v5_new_formal', 'new_families', costs))
    to_csv(RESULTS / 'branch_metrics.csv', rows)
    to_csv(RESULTS / 'summary.csv', list(summary(rows)))
    to_csv(RESULTS / 'paired.csv', list(pairs(rows)))
    if (RESULTS / 'evaluator_audit.csv').is_file():
        to_csv(RESULTS / 'sensitivity.csv', list(sensitivity(rows)))
    guard_rows = [{key: row[key] for key in ('intervention_id', 'cohort', 'stratum', 'guard_readiness',
                  'guard_rules', 'guard_checked', 'guard_allow', 'guard_unknown', 'guard_block',
                  'guard_same_endpoint_proposals', 'application_violation_events', 'supervisor_violation_events',
                  'guard_confirmed_conflict', 'guard_confirmed_nonconflict', 'guard_unverified_block',
                  'guard_recovered', 'trace')} for row in rows if row['arm'] == 'G5']
    if guard_rows:
        to_csv(RESULTS / 'guard_online.csv', guard_rows)
    paid = {}
    for run, measures in costs.items():
        if not run.startswith('v5_'):
            continue
        phase = next((key for key in ('v5_new_formal', 'v5_formal', 'v5_pilot') if run.startswith(key)), 'v5_new')
        paid.setdefault(phase, {}).setdefault(run.rsplit('_', 1)[-1], Counter()).update(measures)
    # Each shared preparation is counted once in the cash ledger, twice only in per-policy comparisons.
    write_json(RESULTS / 'budget.json', {'actual_cumulative': budget, 'v5_true_use_by_phase': paid})
    print(Counter((r['cohort'], r['status']) for r in rows), flush=True)


if __name__ == '__main__':
    main()
