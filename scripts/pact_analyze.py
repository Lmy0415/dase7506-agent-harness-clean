"""Reconstruct PACT tables from the frozen manifest, independent grades and receipts."""

import collections
import csv
import hashlib
import json
import math
import random
import statistics

from src.analyze import RESAMPLES, SEED, cost_by_run, percentile, to_csv
from src.batch import read
from src.model import LEDGER, ROOT
from src.pact_cases import ARMS, BOUNDARIES, MANIFEST, RAW
from src.pact_runner import LIMIT, SETTINGS, occupation
from src.pact_score import RESULTS, steps
from src.runner import write_json

METRICS = ('arr', 'disposition', 'report', 'required_ask', 'unnecessary_ask', 'unauthorized_repair',
           'post_violation', 'independent', 'priority', 'retained', 'official_revised_final')


def records(costs):
    config = read(SETTINGS)
    for item in read(MANIFEST)['tasks']:
        n = item['intervention_id']
        for boundary, order in item['method_order'].items():
            for method in order:
                raw = RAW / item['stage'] / f'case_{n}' / boundary
                path = raw / f'{method}.json'
                trace, grade = read(path), read(raw / f'{method}.score.json')
                billed = costs.get(trace.get('run_id', f"pact_{item['stage']}_{n}_{boundary}_{method}"), {})
                if trace and trace.get('start'):
                    start = item['boundary'][boundary]
                    assert all(start[k] == trace['start'][k] for k in trace['start'])
                    assert trace['attempted_calls'] <= config['calls_per_branch_including_assessment_and_retry']
                    assert all(t['system_fingerprint'] == config['provider_receipt']['system_fingerprint']
                               and t['usage']['completion_tokens'] <= config['max_output_tokens']
                               for t in trace['turns'])
                audit = [event for event in steps(trace) if event['tool'] in ('report_conflict', 'request_decision')
                         and event['http_status'] == 200] if trace else []
                gate = [event for event in steps(trace) if 'gate' in event] if trace else []
                assert sum(e['gate']['decision'] == 'reject' for e in gate) == grade.get('guard_rejections', 0)
                yield {'stage': item['stage'], 'intervention_id': n, 'family_id': item['family_id'],
                       'slot': item['slot'], 'stratum': item['stratum'], 'boundary': boundary, 'method': method,
                       'status': 'scored' if grade else 'missing', 'unknown_key_condition': int(not grade),
                       'expected': grade.get('expected'), **{k: int(grade[k]) if grade.get(k) is not None else
                                                           (0 if k == 'arr' else None) for k in METRICS},
                       'reports_logged': sum(e['tool'] == 'report_conflict' for e in audit),
                       'decision_requests_logged': sum(e['tool'] == 'request_decision' for e in audit),
                       'automatic_messages': len(trace.get('automatic_events', [])),
                       'gate_checked': len(gate), 'gate_rejected': grade.get('guard_rejections'),
                       'declared_scope_candidate_blocks': grade.get('blocked_allowed_scope_candidates'),
                       'verified_guard_false_positive': grade.get('guard_false_positive'),
                       'unverified_reports': grade.get('unverified_reports'),
                       'submitted_writes': grade.get('submitted_writes'), 'stop_reason': trace.get('stop_reason'),
                       'initial_boundary_state': next((x['boundary_state'] for x in trace.get('control', [])
                                                       if x['action'] == 'classify'), None),
                       'final_boundary_state': trace.get('final_task_states', {}).get('boundary'),
                       'attempted_model_calls': trace.get('attempted_calls'),
                       'model_calls': billed.get('calls', 0), 'input_tokens': billed.get('input_tokens', 0),
                       'output_tokens': billed.get('output_tokens', 0), 'peak_nano_usd': billed.get('peak_nano_usd', 0),
                       'offpeak_estimate_nano_usd': billed.get('scheduled_nano_usd', 0),
                       'elapsed_seconds': trace.get('wall_seconds'),
                       'trace': str(path.relative_to(ROOT))}


def aggregate(rows):
    for stage in ('formal', 'pilot'):
        for stratum in ('all', 'natural', 'controlled'):
            for boundary in BOUNDARIES:
                for method in ARMS:
                    group = [r for r in rows if r['stage'] == stage and r['boundary'] == boundary and r['method'] == method
                             and (stratum == 'all' or r['stratum'] == stratum)]
                    if not group:
                        continue
                    record = {'stage': stage, 'stratum': stratum, 'boundary': boundary, 'method': method,
                              'n': len(group), 'scored': sum(r['status'] == 'scored' for r in group),
                              'missing': sum(r['status'] != 'scored' for r in group)}
                    for metric in METRICS:
                        known = [r[metric] for r in group if r[metric] is not None]
                        record[metric] = sum(known)
                        record[metric + '_n'] = len(known)
                    for metric in ('model_calls', 'input_tokens', 'output_tokens', 'peak_nano_usd', 'gate_checked',
                                   'gate_rejected', 'declared_scope_candidate_blocks', 'reports_logged',
                                   'decision_requests_logged', 'automatic_messages', 'unverified_reports'):
                        record[metric] = sum(r[metric] or 0 for r in group)
                    durations = [r['elapsed_seconds'] for r in group if r['elapsed_seconds'] is not None]
                    record['median_seconds'] = statistics.median(durations) if durations else None
                    yield record


def contrasts(rows):
    main = [r for r in rows if r['stage'] == 'formal']
    for stratum in ('all', 'natural', 'controlled'):
        group = [r for r in main if stratum == 'all' or r['stratum'] == stratum]
        families = sorted({r['family_id'] for r in group})
        values = {(r['family_id'], r['boundary'], r['method']): r['arr'] for r in group}
        n = len(families)
        for against in ('P', 'A'):
            for bound in (*BOUNDARIES, 'POST_minus_PRE'):
                delta = lambda f, b: values[f, b, 'PACT'] - values[f, b, against]
                nums = [delta(f, bound) if bound in BOUNDARIES else delta(f, 'POST') - delta(f, 'PRE') for f in families]
                rng = random.Random(SEED)
                replicates = sorted(100 * sum(rng.choices(nums, k=n)) / n for _ in range(RESAMPLES))
                wins, losses = sum(d > 0 for d in nums), sum(d < 0 for d in nums)
                discordant = wins + losses
                p = min(1, 2 * sum(math.comb(discordant, k) for k in range(min(wins, losses) + 1)) /
                        2**discordant) if bound in BOUNDARIES and discordant else None
                yield {'stratum': stratum, 'boundary': bound, 'first': 'PACT', 'second': against, 'families': n,
                       'wins': wins, 'losses': losses, 'ties': nums.count(0), 'net': sum(nums),
                       'delta_pp': 100 * sum(nums) / n, 'low_95': percentile(replicates, .025),
                       'high_95': percentile(replicates, .975), 'exact_mcnemar_unadjusted': p}


def audit_candidates(rows):
    """Make a blind packet for human review of every uncertain report and structured claim."""
    reports = []
    mapping = {}
    for row in rows:
        if row['status'] != 'scored':
            continue
        path = ROOT / row['trace']
        trace = read(path)
        grade = read(path.with_suffix('.score.json'))
        recorded = steps(trace)
        for i, event in enumerate(recorded):
            if event['tool'] not in ('report_conflict', 'request_decision') or event['http_status'] != 200:
                continue
            code = hashlib.sha256(f"pact-review/{row['trace']}/{i}".encode()).hexdigest()[:12]
            reports.append({'id': code, 'intervention_id': row['intervention_id'], 'boundary': row['boundary'],
                            'tool': event['tool'], 'arguments': event['request'],
                            'structured_match': i in (grade['report_indices'] if event['tool'] == 'report_conflict'
                                                        else grade['ask_indices'])})
            mapping[code] = {'trace': row['trace'], 'event_index': i}
    random.Random(SEED).shuffle(reports)
    write_json(RAW / 'blind_reports.json', reports)
    write_json(RAW / 'blind_reports_key.json', mapping)
    print('blind packet communications:', len(reports))


def main():
    costs, cumulative = cost_by_run()
    cases = list(records(costs))
    assert len({(r['stage'], r['family_id'], r['boundary'], r['method']) for r in cases}) == len(cases)
    to_csv(RESULTS / 'branch_metrics.csv', cases)
    to_csv(RESULTS / 'summary.csv', list(aggregate(cases)))
    to_csv(RESULTS / 'paired.csv', list(contrasts(cases)))
    with LEDGER.open() as fd:
        project_total, pact_total, pending = occupation(map(json.loads, fd))
    assert project_total == cumulative['total_peak_nano_usd'] + cumulative['outstanding_reservations_nano_usd']
    by_stage = collections.defaultdict(collections.Counter)
    for name, entry in costs.items():
        if name.startswith('pact_'):
            _, stage, _, boundary, method = name.split('_')
            by_stage[stage][f'{boundary}/{method}'] += entry['peak_nano_usd']
            by_stage[stage]['peak_nano_usd'] += entry['peak_nano_usd']
            by_stage[stage]['receipts'] += entry['calls']
            by_stage[stage]['estimated_schedule_nano_usd'] += entry['scheduled_nano_usd']
    assert sum(s['peak_nano_usd'] for s in by_stage.values()) + pending == pact_total <= LIMIT
    write_json(RESULTS / 'budget.json', {'project': cumulative, 'project_occupied_upper_nano_usd': project_total,
               'pact_occupied_upper_nano_usd': pact_total, 'pact_pending_nano_usd': pending,
               'pact_limit_nano_usd': LIMIT, 'pact_by_stage': dict(by_stage)})
    picks = {
        'payment_keep': 'same SMS pending versus committed; preserve completed payment',
        'cart_only': 'guard allowed a redundant write to the retained cart',
        'selective': 'report and ask while independent work continues; priority and dependency',
        'alarm_repair': 'exact committed alarm may be removed only after explicit authorization',
    }
    to_csv(RESULTS / 'case_index.csv', [
        {k: r[k] for k in ('intervention_id', 'family_id', 'slot', 'boundary', 'method', 'arr', 'expected',
                           'report', 'required_ask', 'independent', 'priority', 'post_violation', 'trace')} |
        {'focus': picks[r['slot']]} for r in cases if r['slot'] in picks and r['stage'] == 'formal'])
    to_csv(RESULTS / 'boundary_checks.csv', [
        {'stage': item['stage'], 'family_id': item['family_id'], 'intervention_id': item['intervention_id'],
         'endpoint': item['endpoint'], 'http_status': evidence['event']['http_status'],
         'observed_transitions': len(evidence['event']['forbidden_transitions']),
         'context_changed': int(evidence['PRE']['context_sha256'] != evidence['POST']['context_sha256']),
         'world_changed': int(evidence['PRE']['state']['model_hashes_sha256'] !=
                              evidence['POST']['state']['model_hashes_sha256']),
         'one_submission': int(evidence['one_submission']), 'model_calls': evidence['model_calls']}
        for item in read(MANIFEST)['tasks'] for evidence in [read(ROOT / item['receipt_evidence'])]])
    first = []
    for item in read(MANIFEST)['tasks']:
        if item['stage'] != 'pilot':
            continue
        for boundary, order in item['method_order'].items():
            for method in order:
                n = item['intervention_id']
                path = RAW / 'pilot_first' / f'case_{n}' / boundary / f'{method}.score.json'
                grade = read(path)
                first.append({'intervention_id': n, 'boundary': boundary, 'method': method,
                              'arr_before_pilot_correction': int(grade['arr']),
                              'disposition_before_pilot_correction': int(grade['disposition']),
                              'independent_before_pilot_correction': int(grade['independent']),
                              'status': 'original technical pilot, superseded scoring audit',
                              'trace': str(path.relative_to(ROOT))})
    to_csv(RESULTS / 'pilot_first.csv', first)
    write_json(RESULTS / 'component_control.json', read(RAW / 'component_control.json'))
    audit_candidates(cases)
    print(collections.Counter((r['stage'], r['status']) for r in cases))


if __name__ == '__main__':
    main()
