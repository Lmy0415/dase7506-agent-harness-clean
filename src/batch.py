"""Run the bounded pilot in queue order and resume from the saved traces."""

import argparse
import fcntl
import json
from collections import Counter
from pathlib import Path
from uuid import uuid4

from scripts.calibrate_alarm import load_case
from src.annotations import ANNOTATIONS
from src.model import ROOT, BudgetLimit
from src.monitor import Monitor
from src.runner import run_branch, run_prefix, write_json

PILOT_TARGET = 8
INDEX = ROOT / 'protocol' / 'candidate_index.jsonl'
BATCH = ROOT / 'artifacts' / 'raw' / 'pilot_batch'
STRATEGIES = ('A', 'B', 'C', 'D')


def read(path):
    return json.loads(path.read_text()) if path.is_file() else {}


def prefix_status(trace):
    probe = trace.get('boundary_probe', {})
    status = probe.get('http_status')
    if type(status) is int and 200 <= status < 300 and probe.get('forbidden_transitions'):
        return 'admitted'
    if trace.get('infrastructure_error') or trace.get('status') == 'started':
        return 'infrastructure_error'
    return 'probe_failed' if trace.get('stop_reason') == 'pending' else 'did_not_propose_boundary'


def resume_attempt(path):
    """Preserve an incomplete attempt, permitting at most two retries."""
    if not path.is_file():
        return True
    previous = read(path)
    if previous.get('status') == 'terminal' and previous.get('infrastructure_error') not in {
        'TransientModelError', 'BudgetLimit',
    }:
        return False
    attempts = sorted(path.parent.glob(f'{path.stem}.attempt-*.json'))
    if len(attempts) >= 2:
        return False
    path.rename(path.with_name(f'{path.stem}.attempt-{len(attempts) + 1}.json'))
    return True


def screen(row, directory, monitor):
    path = directory / 'prefix.json'
    if path.is_file():
        status = prefix_status(read(path))
        if status != 'infrastructure_error' or not resume_attempt(path):
            return status
        # A crash or transient error may have occurred during the isolated probe.
        checkpoint = directory / 'checkpoint'
        if checkpoint.is_dir():
            checkpoint.rename(directory / f'checkpoint.attempt-{len(list(directory.glob("prefix.attempt-*.json")))}')
    try:
        run_prefix(row, directory, monitor)
    except BudgetLimit:
        raise
    except Exception as error:
        print(f"Prefix {row['intervention_idx']} raised {type(error).__name__}; trace retained.", flush=True)
    return prefix_status(read(path))


def finish_case(row, evaluator, candidate, directory, monitor, retained, order=None):
    offset = (candidate['queue_position'] - 1) % 3
    if order is None:
        order = STRATEGIES[offset:3] + STRATEGIES[:offset] + ('D',)
    for strategy in order:
        path = directory / f'{strategy}.json'
        if read(path).get('score') is not None or not resume_attempt(path):
            continue
        try:
            run_branch(row, evaluator, directory, strategy, monitor, retained)
        except BudgetLimit:
            raise
        except Exception as error:
            print(f"Branch {row['intervention_idx']}/{strategy} raised {type(error).__name__}; trace retained.", flush=True)
    return {strategy: 'scored' if read(directory / f'{strategy}.json').get('score') is not None else 'incomplete'
            for strategy in order}


def pilot(import_existing):
    progress_path = BATCH / 'progress.json'
    progress = read(progress_path)
    candidates = [item for item in map(json.loads, INDEX.read_text().splitlines()) if item['split'] == 'pilot']
    admitted = {item['family_id']: key for key, item in progress.items() if item['status'] == 'admitted'}

    if import_existing:
        source = import_existing.resolve()
        prefix = read(source / 'prefix.json')
        item = next(i for i in candidates if i['intervention_id'] == prefix.get('intervention_id'))
        key = str(item['intervention_id'])
        if prefix_status(prefix) != 'admitted' or any(not read(source / f'{a}.json').get('score') for a in STRATEGIES):
            raise ValueError('The imported pilot case lacks a verified prefix or one of the four scored branches.')
        if item['family_id'] in admitted and admitted[item['family_id']] != key:
            raise ValueError('A different variant of the imported pilot family is already admitted.')
        if key in progress and Path(progress[key]['directory']) != source:
            raise ValueError('This intervention points to a different directory in the pilot ledger.')
        progress[key] = {**item, 'status': 'admitted', 'directory': str(source),
                         'branches': {a: 'scored' for a in STRATEGIES}, 'imported': True}
        admitted[item['family_id']] = key
        write_json(progress_path, progress)

    for item in candidates:
        intervention = item['intervention_id']
        family = item['family_id']
        key = str(intervention)
        if family in admitted and admitted[family] != key:
            continue
        if family not in admitted and len(admitted) >= PILOT_TARGET:
            continue
        if intervention not in ANNOTATIONS:
            progress.setdefault(key, {**item, 'status': 'annotation_unavailable'})
            continue
        old = progress.get(key, {})
        if old.get('branches') and set(old['branches'].values()) == {'scored'}:
            continue
        if old.get('status') in {'did_not_propose_boundary', 'probe_failed'}:
            continue
        row, evaluator = load_case(intervention)
        rules, retained = ANNOTATIONS[intervention]
        monitor = Monitor(rules)
        directory = Path(old['directory']) if old.get('directory') else BATCH / f'pilot_{intervention}_{uuid4().hex[:8]}'
        progress[key] = {**item, 'status': 'screening', 'directory': str(directory)}
        write_json(progress_path, progress)
        status = screen(row, directory, monitor)
        record = progress[key]
        record['status'] = status
        trace = read(directory / 'prefix.json')
        record['prefix_stop'] = trace.get('stop_reason')
        record['prefix_calls'] = len(trace.get('turns', []))
        if status == 'admitted':
            admitted[family] = key
        write_json(progress_path, progress)
        print(f'{intervention} {status} ({record["prefix_calls"]} calls)', flush=True)
        if status == 'admitted':
            record['branches'] = finish_case(row, evaluator, item, directory, monitor, retained)
            write_json(progress_path, progress)
            print(f'{intervention} {record["branches"]}', flush=True)

    write_json(progress_path, progress)
    states = Counter(item['status'] for item in progress.values())
    print(json.dumps({'case_states': dict(states), 'target': PILOT_TARGET}, sort_keys=True), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--import-existing', type=Path, help='Adopt an already completed pilot case into the ledger.')
    args = parser.parse_args()
    BATCH.mkdir(parents=True, exist_ok=True)
    with (BATCH / 'batch.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        pilot(args.import_existing)


if __name__ == '__main__':
    main()
