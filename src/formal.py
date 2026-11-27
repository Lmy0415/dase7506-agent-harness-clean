"""Freeze the formal design, screen prefixes, then run the locked manifest."""

import argparse
import fcntl
import hashlib
import json
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import os
from pathlib import Path

from scripts.calibrate_alarm import load_case
from src.annotations import ANNOTATIONS
from src.batch import BATCH as PILOT, INDEX, finish_case, read, screen
from src.checkpoint import digest
from src.model import BUDGET, LEDGER, MODEL, ROOT
from src.monitor import Monitor
from src.runner import (
    FOLLOW_PLAN, FULL, INITIAL, LOCAL, OUTPUT_TOKENS, PREFIX_CALLS, REPAIR, SEED,
    SUFFIX_CALLS, SYSTEM, write_json,
)

PROTOCOL = ROOT / 'protocol'
FORMAL = ROOT / 'artifacts' / 'raw' / 'formal'
SETTINGS = PROTOCOL / 'settings.json'
MANIFEST = PROTOCOL / 'formal_manifest.json'
DESIGN_FILES = (
    'protocol/candidate_index.jsonl', 'protocol/candidate_census.json',
    'src/annotations.py', 'src/batch.py', 'src/checkpoint.py', 'src/env_adapter.py',
    'src/model.py', 'src/monitor.py', 'src/runner.py', 'src/strategies.py',
    'src/formal.py', 'scripts/calibrate_alarm.py',
)
TARGET, SCREEN_CAP, WORKERS = 40, 100, 2


def file_hashes():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in DESIGN_FILES}


def ledger_summary():
    latest = {}
    reserved = {}
    for item in map(json.loads, LEDGER.read_text().splitlines()):
        key = item['request_id']
        if item['status'] == 'reserved':
            reserved[key] = item
        latest[key] = item
    settled = {key: item for key, item in latest.items() if item['status'] == 'settled_peak_price'}
    consumed = sum(item['amount_nano_usd'] for item in settled.values())
    outstanding = sum(reserved[key]['amount_nano_usd'] for key in reserved
                      if latest[key]['status'] not in {'settled_peak_price', 'rejected'})
    return settled, reserved, consumed, outstanding


def freeze_settings():
    if SETTINGS.exists():
        raise FileExistsError('Settings already frozen.')
    pilot = read(PILOT / 'progress.json')
    completed = [item for item in pilot.values() if item.get('branches')
                 and set(item['branches'].values()) == {'scored'}]
    unique = {item['family_id'] for item in completed}
    if len(unique) != len(completed) or len(completed) < 6:
        raise RuntimeError('At least six independent pilot cases must have completed.')
    settled, reserved, consumed, outstanding = ledger_summary()
    batches = {Path(item['directory']).name for item in completed}
    pilot_specs = {
        reserved[key]['purpose'].rsplit('_', 1)[0] for key in settled if key in reserved
        and reserved[key]['purpose'].rsplit('_', 1)[0] in batches
    }
    if pilot_specs != batches:
        raise RuntimeError('An eligible pilot case has no provider billing record.')
    costs = Counter()
    for key, item in settled.items():
        purpose = reserved[key]['purpose']
        case, _, arm = purpose.rpartition('_')
        if case in batches:
            costs[arm] += item['amount_nano_usd']
    n = len(completed)
    # Reserve twice the observed mean cost. Screening uses the cap, suffixes the target.
    screen_estimate = (2 * costs['prefix'] * SCREEN_CAP + n - 1) // n
    abc_estimate = (2 * sum(costs[arm] for arm in 'ABC') * TARGET + n - 1) // n
    d_all_estimate = (2 * costs['D'] * TARGET + n - 1) // n
    d_mode = 'all' if consumed + outstanding + screen_estimate + abc_estimate + d_all_estimate < BUDGET else 'balanced_12'
    run_limit = TARGET if consumed + outstanding + screen_estimate + abc_estimate < BUDGET else 28
    result = {
        'protocol_version': 1, 'model_id': MODEL, 'provider_version_at_verification': 'DeepSeek-V4.1-Flash-1017',
        'thinking': 'disabled', 'temperature': 'provider fixed in non-thinking mode', 'seed_appworld': SEED,
        'model_seed': None, 'max_prefix_calls': PREFIX_CALLS, 'max_suffix_calls_including_planning': SUFFIX_CALLS,
        'max_output_tokens_per_call': OUTPUT_TOKENS, 'max_requests_in_execution_turn': 1,
        'max_plan_repairs': 1, 'plan_failure': 'native continuation',
        'prompts': {'system': SYSTEM, 'initial': INITIAL, 'B': FULL, 'C': LOCAL, 'repair': REPAIR, 'remaining': FOLLOW_PLAN},
        'candidate_source': read(PROTOCOL / 'candidate_census.json'),
        'screen_rule': 'First confirmed pending effect; first admitted variant per family in candidate order.',
        'monitoring': 'Reviewed rules in src/annotations.py; the environment-only probe confirms a committed effect.',
        'screen_model_attempt_cap': SCREEN_CAP, 'formal_target': run_limit, 'preferred_count_per_stratum': run_limit // 2,
        'd_selection': d_mode, 'd_selection_seed': SEED, 'strategy_order': 'rotate ABC by queue position; then D',
        'formal_worker_processes': WORKERS,
        'missing_or_unknown': 'Formal denominator fixed by manifest. Score missing final/strict as unsuccessful; violation unknown.',
        'pilot_completed': sorted(item['intervention_id'] for item in completed),
        'pilot_cost_upper_nano_usd_by_step': dict(costs),
        'project_budget_nano_usd': BUDGET, 'budget_before_formal_nano_usd': consumed + outstanding,
        'cost_projection_nano_usd': {'screen': screen_estimate, 'ABC': abc_estimate, 'D_all': d_all_estimate},
        'file_sha256': file_hashes(),
    }
    write_json(SETTINGS, result)
    print(json.dumps({'frozen_settings': str(SETTINGS), 'pilot_n': n, 'formal_target': run_limit, 'D': d_mode}))


def settings():
    if not SETTINGS.is_file():
        raise RuntimeError('Freeze settings after the completed pilot before formal screening.')
    result = read(SETTINGS)
    if result['file_sha256'] != file_hashes():
        raise RuntimeError('Current execution code or candidate index differs from the frozen design.')
    return result


def formal_candidates():
    return [item for item in map(json.loads, INDEX.read_text().splitlines()) if item['split'] == 'formal']


def formal_screen(frozen):
    if MANIFEST.exists():
        raise RuntimeError('The formal manifest already exists.')
    log = FORMAL / 'screening.json'
    progress = read(log)
    candidates = formal_candidates()
    admitted = {item['family_id']: item for item in progress.values() if item['status'] == 'admitted'}
    attempted = sum('directory' in item for item in progress.values())
    admitted_by_kind = Counter(item['stratum'] for item in admitted.values())
    for prefer_balance, item in [(True, row) for row in candidates] + [(False, row) for row in candidates]:
        intervention = item['intervention_id']
        family = item['family_id']
        key = str(intervention)
        if family in admitted or len(admitted) >= frozen['formal_target']:
            continue
        if prefer_balance and admitted_by_kind[item['stratum']] >= frozen['preferred_count_per_stratum']:
            continue
        previous = progress.get(key, {})
        if previous.get('status') in {'did_not_propose_boundary', 'probe_failed'}:
            continue
        if intervention not in ANNOTATIONS:
            progress.setdefault(key, {**item, 'status': 'annotation_unavailable'})
            continue
        if 'directory' not in previous:
            if attempted >= frozen['screen_model_attempt_cap']:
                continue
            attempted += 1
        row, _ = load_case(intervention)
        rules, _ = ANNOTATIONS[intervention]
        directory = FORMAL / f'formal_{intervention}'
        record = {**item, 'status': 'screening', 'directory': str(directory.relative_to(ROOT))}
        progress[key] = record
        write_json(log, progress)
        status = screen(row, directory, Monitor(rules))
        evidence = read(directory / 'prefix.json')
        record['status'] = status
        record['prefix_stop'] = evidence.get('stop_reason')
        record['prefix_calls'] = len(evidence.get('turns', []))
        if status == 'admitted':
            admitted[family] = record
            admitted_by_kind[item['stratum']] += 1
        write_json(log, progress)
        print(f'{intervention} {status} ({record["prefix_calls"]} calls)', flush=True)
    write_json(log, progress)
    counts = Counter(item['status'] for item in progress.values())
    write_json(FORMAL / 'screen_status.json', {'status': 'finished', 'counts': dict(counts),
                                               'attempted': attempted, 'eligible_families': len(admitted)})
    print(json.dumps({'attempted': attempted, 'counts': dict(counts)}), flush=True)


def freeze_manifest(frozen):
    if MANIFEST.is_file():
        raise FileExistsError('Formal manifest already frozen.')
    summary = read(FORMAL / 'screen_status.json')
    if summary.get('status') != 'finished':
        raise RuntimeError('Complete formal prefix screening before freezing the manifest.')
    progress = read(FORMAL / 'screening.json')
    admitted = sorted((item for item in progress.values() if item['status'] == 'admitted'),
                      key=lambda item: item['queue_position'])
    if not admitted:
        raise RuntimeError('There are no admitted formal tasks.')
    if len({item['family_id'] for item in admitted}) != len(admitted):
        raise RuntimeError('A formal task family has multiple admitted variants.')
    d = set()
    if frozen['d_selection'] == 'all' or len(admitted) <= 12:
        d.update(item['intervention_id'] for item in admitted)
    else:
        by_kind = {kind: sorted((item for item in admitted if item['stratum'] == kind),
                                key=lambda item: digest([SEED, item['intervention_id']]))
                   for kind in ('Drop', 'Swap')}
        for position in range(max(map(len, by_kind.values()))):
            for group in by_kind.values():
                if position < len(group) and len(d) < 12:
                    d.add(group[position]['intervention_id'])
    manifest_rows = []
    for item in admitted:
        prefix = read(ROOT / item['directory'] / 'prefix.json')
        offset = (item['queue_position'] - 1) % 3
        order = list('ABC'[offset:] + 'ABC'[:offset])
        if item['intervention_id'] in d:
            order.append('D')
        manifest_rows.append({**item, 'context_sha256': prefix['context_sha256'], 'state': prefix['state'], 'order': order})
    result = {'settings_sha256': hashlib.sha256(SETTINGS.read_bytes()).hexdigest(), 'screening_summary': summary,
              'tasks': manifest_rows}
    write_json(MANIFEST, result)
    print(json.dumps({'formal_manifest': str(MANIFEST), 'pairs': len(admitted), 'D': len(d)}), flush=True)


def run_formal_case(item):
    os.environ['IPYTHONDIR'] = str(FORMAL / f'worker-{os.getpid()}')
    intervention = item['intervention_id']
    row, evaluator = load_case(intervention)
    rules, retained = ANNOTATIONS[intervention]
    directory = ROOT / item['directory']
    prefix = read(directory / 'prefix.json')
    if prefix.get('context_sha256') != item['context_sha256'] or prefix.get('state') != item['state']:
        raise RuntimeError(f'Frozen prefix metadata mismatch for intervention {intervention}.')
    branches = finish_case(row, evaluator, item, directory, Monitor(rules), retained, order=item['order'])
    print(f'{intervention} {branches}', flush=True)


def run_formal():
    manifest = read(MANIFEST)
    if manifest.get('settings_sha256') != hashlib.sha256(SETTINGS.read_bytes()).hexdigest():
        raise RuntimeError('The manifest does not match the frozen settings.')
    with ProcessPoolExecutor(max_workers=WORKERS) as pool:
        for _ in pool.map(run_formal_case, manifest['tasks']):
            pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['freeze-settings', 'screen', 'freeze-manifest', 'run'])
    args = parser.parse_args()
    FORMAL.mkdir(parents=True, exist_ok=True)
    with (FORMAL / 'formal.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.phase == 'freeze-settings':
            freeze_settings()
        elif args.phase == 'screen':
            formal_screen(settings())
        elif args.phase == 'freeze-manifest':
            freeze_manifest(settings())
        else:
            settings()
            run_formal()


if __name__ == '__main__':
    main()
