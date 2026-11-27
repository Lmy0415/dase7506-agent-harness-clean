"""Rebuild V4 outcome, cost, guard, and paired tables from local traces."""

import math
import random
from collections import Counter

from src.analyze import RESAMPLES, SEED, cost_by_run, events, percentile, repeat_counts, to_csv
from src.batch import read
from src.harness_v4 import ARMS, MANIFEST, RAW, SETTINGS, scheduled, pilot_cases, pilot_phase
from src.model import ROOT
from src.expansion import sha
from src.runner import write_json

RESULTS = ROOT / 'results' / 'harness_v4'
COMPARISONS = (('C+', 'C'), ('C+', 'R'), ('R', 'A'), ('B', 'A'), ('C', 'B'), ('C', 'A'), ('C++', 'C+'))


def guard_audit(prefix, trace):
    """Classify only blocks independently verifiable at the original checkpoint."""
    prior_executed = False
    probe = prefix.get('boundary_probe', {})
    for event in events(trace):
        request = event.get('request') or {}
        response = event.get('response')
        if isinstance(response, dict) and response.get('blocked') is True:
            if not prior_executed and request == probe.get('request') and 200 <= probe.get('http_status', 0) < 300:
                yield 'confirmed_conflict' if probe.get('forbidden_transitions') else 'confirmed_nonconflict'
            else:
                yield 'unknown'
        elif isinstance(request, dict) and request.get('api') and 'state_before' in event:
            # A previous environment operation may have changed execution context.
            # This audit cannot prove the counterfactual after such a transition.
            prior_executed = True


def branch(item, arm, phase, usage):
    source = ROOT / item['directory']
    path = RAW / phase / f"case_{item['intervention_id']}" / f'{arm}.json' if arm in ARMS else source / f'{arm}.json'
    trace = read(path)
    prefix = read(source / 'prefix.json')
    score = trace.get('score') or {}
    scored = trace.get('score') is not None
    if trace and (trace.get('intervention_id') != item['intervention_id'] or trace.get('strategy') != arm):
        raise ValueError(f'Incorrect branch identity at {path}.')
    if scored and arm != 'D' and any(trace.get(key) != item[key] for key in ('state', 'context_sha256')):
        raise ValueError(f'Checkpoint mismatch at {path}.')
    tool_events = events(trace)
    committed = [event for event in tool_events if event.get('forbidden_transitions')]
    if scored and arm != 'D' and score['committed_violation'] != bool(committed):
        raise ValueError(f'Committed violation differs from the frozen score at {path}.')
    apps = {event.get('request', {}).get('app') for event in committed}
    determinate = scored and arm != 'D'
    counts = Counter(record['decision'] for record in trace.get('guard_decisions', []))
    blocked = Counter(guard_audit(prefix, trace))
    if counts['block'] != sum(blocked.values()):
        raise ValueError(f'Missing guard evidence at {path}.')
    repeated, changing = repeat_counts(prefix if arm != 'D' else {}, trace)
    retained = score.get('retained_checks', {})
    costs = usage.get(trace.get('run_id') or f'{path.parent.name}_{arm}', Counter())
    attempts = [turn['plan_parse_error'] for turn in trace.get('turns', []) if 'plan_parse_error' in turn]
    return {
        'intervention_id': item['intervention_id'], 'family_id': item['family_id'], 'cohort': item['cohort'],
        'stratum': item['stratum'], 'strategy': arm, 'status': 'scored' if scored else 'incomplete' if trace else 'missing',
        'stop_reason': trace.get('stop_reason'), 'infrastructure_error': trace.get('infrastructure_error'),
        'final_success': int(score.get('revised_final_success') is True),
        'strict_success': int(score.get('strict_success') is True) if arm != 'D' else None,
        'official_success': int(score.get('official_pass') is True),
        'violation': int(bool(committed)) if determinate else None,
        'supervisor_violation': int('supervisor' in apps) if determinate else None,
        'application_violation': int(bool(apps - {None, 'supervisor'})) if determinate else None,
        'other_violation': int(None in apps) if determinate else None,
        'application_sensitive_strict': int(bool(score.get('revised_final_success'))
                                            and score.get('retained_satisfied') is not False
                                            and not (apps - {'supervisor'})) if arm != 'D' else None,
        'retained_pass': sum(value is True for value in retained.values()),
        'retained_known': sum(value is not None for value in retained.values()),
        'retained_total': len(retained),
        'fallback': int(trace.get('fallback') is True),
        'format_errors': len(attempts),
        'evidence_validation_errors': sum(any(token in error.lower() for token in ('evidence', 'completion', 'progress'))
                                          for error in attempts),
        'calls': costs['calls'], 'input_tokens': costs['input_tokens'], 'output_tokens': costs['output_tokens'],
        'peak_nano_usd': costs['peak_nano_usd'], 'scheduled_nano_usd': costs['scheduled_nano_usd'],
        'unsettled_or_rejected': costs['unsettled_or_rejected_calls'],
        'wall_seconds': trace.get('wall_seconds'),
        'tool_events': len(tool_events), 'repeated_requests': repeated, 'repeats_changing_state': changing,
        'guard_signature': int(trace.get('guard_signature') is not None) if arm == 'C++' else None,
        'allow': counts['allow'], 'unknown': counts['unknown'], 'block': counts['block'],
        'confirmed_conflict': blocked['confirmed_conflict'],
        'confirmed_nonconflict': blocked['confirmed_nonconflict'],
        'unknown_block': blocked['unknown'],
        'trace': str(path.relative_to(ROOT)) if trace else None,
        'preserved_attempts': len(list(path.parent.glob(f'{arm}.attempt-*.json'))),
    }


def cohorts(rows):
    for cohort in ('all', 'original', 'expansion', 'pilot'):
        population = [r for r in rows if cohort == 'all' or r['cohort'] == cohort]
        for stratum in ('all', 'Swap', 'Drop'):
            selected = [r for r in population if stratum == 'all' or r['stratum'] == stratum]
            if selected:
                yield cohort, stratum, selected


def summarize(rows):
    for cohort, stratum, selected in cohorts(rows):
        for arm in ('A', 'B', 'C', *ARMS, 'D'):
            sample = [row for row in selected if row['strategy'] == arm]
            if not sample:
                continue
            determinable = [row for row in sample if row['violation'] is not None]
            finals = [row for row in determinable if row['final_success']]
            success_key = 'final_success' if arm == 'D' else 'strict_success'
            successful = [r for r in sample if r[success_key]]
            totals = {name: sum(row[name] or 0 for row in sample) for name in (
                'final_success', 'strict_success', 'official_success', 'violation', 'supervisor_violation',
                'application_violation', 'other_violation', 'application_sensitive_strict',
                'retained_pass', 'retained_known', 'retained_total', 'fallback', 'format_errors',
                'evidence_validation_errors', 'calls', 'input_tokens', 'output_tokens', 'peak_nano_usd',
                'scheduled_nano_usd', 'wall_seconds', 'tool_events', 'repeated_requests',
                'repeats_changing_state', 'guard_signature', 'allow', 'unknown', 'block',
                'confirmed_conflict', 'confirmed_nonconflict', 'unknown_block',
            )}
            yield {
                'cohort': cohort, 'stratum': stratum, 'strategy': arm, 'n': len(sample),
                'scored': sum(row['status'] == 'scored' for row in sample),
                'violation_known': len(determinable), 'final_violation_n': len(finals),
                'final_with_violation': sum(r['violation'] for r in finals),
                'success_cost_n': len(successful), 'success_peak_nano_usd': sum(r['peak_nano_usd'] for r in successful),
                **totals,
            }


def paired(rows):
    for cohort, stratum, group in cohorts(rows):
        by_arm = {arm: {row['family_id']: row for row in group if row['strategy'] == arm} for arm in (*'ABC', *ARMS)}
        for first, second in COMPARISONS:
            both = sorted(by_arm[first].keys() & by_arm[second].keys())
            if not both:
                continue
            if len(both) != len(by_arm[first]) or len(both) != len(by_arm[second]):
                raise ValueError(f'Incomplete paired design for {cohort}, {first}/{second}.')
            for outcome in ('strict_success', 'violation'):
                availabilities = ('all_manifest', 'both_scored') if outcome == 'strict_success' else ('both_known',)
                for scope in availabilities:
                    pairs = [(by_arm[first][key], by_arm[second][key]) for key in both]
                    if scope == 'both_scored':
                        pairs = [(a, b) for a, b in pairs if a['status'] == b['status'] == 'scored']
                    if scope == 'both_known':
                        pairs = [(a, b) for a, b in pairs if a[outcome] is not None and b[outcome] is not None]
                    if not pairs:
                        continue
                    scores = [(a[outcome], b[outcome]) for a, b in pairs]
                    switches = Counter(scores)
                    effects = [a - b for a, b in scores]
                    n = len(effects)
                    rng = random.Random(SEED)
                    bootstrap = sorted(sum(rng.choices(effects, k=n)) * 100 / n for _ in range(RESAMPLES))
                    up, down = switches[1, 0], switches[0, 1]
                    exact_p = min(1, 2 * sum(math.comb(up + down, i) for i in range(min(up, down) + 1)) / 2**(up + down))
                    yield {
                        'cohort': cohort, 'stratum': stratum, 'comparison': f'{first} vs {second}',
                        'outcome': outcome, 'denominator': scope, 'n': n, 'first_only': up, 'second_only': down,
                        'both_positive': switches[1, 1], 'both_negative': switches[0, 0],
                        'difference_pp': sum(effects) * 100 / n, 'lower_95_pp': percentile(bootstrap, .025),
                        'upper_95_pp': percentile(bootstrap, .975), 'exact_mcnemar_p_unadjusted': exact_p,
                    }


def main():
    manifest = read(MANIFEST)
    if manifest.get('settings_sha256') != sha(SETTINGS):
        raise ValueError('V4 manifest does not match its settings.')
    usage, budget = cost_by_run()
    rows = [branch(item, arm, 'v4_formal', usage)
            for item in manifest['tasks'] for arm in (*item['order'], *item['v4_order'])]
    pilot = [branch(item, arm, pilot_phase(arm), usage)
             for item in scheduled(pilot_cases()) for arm in item['v4_order']]
    first_pilot = [branch(item, arm, 'v4_pilot', usage)
                   for item in scheduled(pilot_cases()) for arm in item['v4_order']]
    to_csv(RESULTS / 'branch_metrics.csv', rows)
    to_csv(RESULTS / 'summary.csv', list(summarize(rows)))
    to_csv(RESULTS / 'paired.csv', list(paired(rows)))
    to_csv(RESULTS / 'guard_audit.csv', [
        {key: row[key] for key in ('intervention_id', 'cohort', 'stratum', 'guard_signature', 'allow', 'unknown',
                                   'block', 'confirmed_conflict', 'confirmed_nonconflict', 'unknown_block', 'trace')}
        for row in rows if row['strategy'] == 'C++'
    ])
    to_csv(RESULTS / 'pilot_metrics.csv', pilot)
    to_csv(RESULTS / 'pilot_first_pass.csv', first_pilot)
    control = read(RAW / 'guard_pilot_control.json')
    if control:
        write_json(RESULTS / 'guard_pilot_control.json', control)
    v4_costs = {}
    for phase in ('v4_pilot', 'v4_confirmation', 'v4_formal'):
        v4_costs[phase] = {}
        for arm in ARMS:
            counter = Counter()
            for key, amounts in usage.items():
                if key.startswith(f'{phase}_') and key.endswith(f'_{arm}'):
                    counter.update(amounts)
            v4_costs[phase][arm] = dict(counter)
    write_json(RESULTS / 'budget.json', {'cumulative': budget, 'v4_calls': v4_costs})
    print(f'Formal {sum(row["status"] == "scored" for row in rows)}/{len(rows)} scored, '
          f'pilot {sum(row["status"] == "scored" for row in pilot)}/{len(pilot)} scored.')


if __name__ == '__main__':
    main()
