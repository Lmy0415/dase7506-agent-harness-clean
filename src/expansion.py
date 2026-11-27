"""Freeze and run a finite A/B/C/D expansion using the original V3 executor."""

import argparse
import fcntl
import hashlib
import json
import os
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from scripts.calibrate_alarm import load_case
from src import analyze, formal
from src.batch import finish_case, read, screen
from src.expansion_annotations import ExpansionMonitor, RULES
from src.model import ROOT
from src.runner import world_factory, write_json

RAW = ROOT / 'artifacts' / 'raw' / 'expansion_v3'
PROGRESS = RAW / 'screening.json'
SETTINGS = ROOT / 'protocol' / 'expansion_settings.json'
MANIFEST = ROOT / 'protocol' / 'expansion_manifest.json'
RESULTS = ROOT / 'results' / 'expansion_v3'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def design():
    original = formal.settings()
    old = read(formal.MANIFEST)
    if old['settings_sha256'] != sha(formal.SETTINGS):
        raise RuntimeError('Original formal settings and manifest differ.')
    attempted = read(formal.FORMAL / 'screening.json')
    admitted = {item['family_id'] for item in old['tasks']}
    candidates = [
        item for item in formal.formal_candidates()
        if item['intervention_id'] in RULES and item['family_id'] not in admitted
        and attempted.get(str(item['intervention_id']), {}).get('status') == 'annotation_unavailable'
    ]
    if set(RULES) != {item['intervention_id'] for item in candidates}:
        raise ValueError('An expansion rule points outside the untried formal index.')
    return {
        'source_settings_sha256': sha(formal.SETTINGS),
        'source_manifest_sha256': sha(formal.MANIFEST),
        'code_sha256': sha(Path(__file__)),
        'rules_sha256': sha(ROOT / 'src' / 'expansion_annotations.py'),
        'model_id': original['model_id'],
        'provider_version': original['provider_version_at_verification'],
        'max_prefix_calls': original['max_prefix_calls'],
        'max_suffix_calls_including_planning': original['max_suffix_calls_including_planning'],
        'max_output_tokens_per_call': original['max_output_tokens_per_call'],
        'scope': 'One bounded reviewed pass in the unchanged formal queue. Use the first confirmed boundary per family, regardless of count.',
        'd_selection': 'all',
        'candidates': candidates,
    }


def monitor(item):
    return ExpansionMonitor(RULES[item['intervention_id']])


def preflight(candidates):
    for item in candidates:
        rule_monitor = monitor(item)
        number = item['intervention_id']
        with world_factory(item['task_id'], f'expansion_preflight_{number}') as world:
            bound = rule_monitor.bind(world)
            bound.observe(world)
            for rule in bound.rules:
                for api in rule['proposal_apis']:
                    app, name = api.split('.')
                    if not callable(getattr(world.apis[app], name, None)):
                        raise ValueError(f'Unknown proposal API {api} on {number}.')
        print(f'{number} preflight passed', flush=True)


def screen_all(candidates):
    progress = read(PROGRESS)
    admitted = {item['family_id'] for item in progress.values() if item['status'] == 'admitted'}
    for item in candidates:
        number = item['intervention_id']
        key = str(number)
        prior = progress.get(key, {})
        if prior.get('status') in {'admitted', 'did_not_propose_boundary', 'probe_failed'}:
            continue
        if item['family_id'] in admitted:
            progress[key] = {**item, 'status': 'another_variant_admitted'}
            write_json(PROGRESS, progress)
            continue
        directory = RAW / f'expansion_{number}'
        record = {**item, 'directory': str(directory.relative_to(ROOT)), 'status': 'screening'}
        progress[key] = record
        write_json(PROGRESS, progress)
        row, _ = load_case(number)
        record['status'] = screen(row, directory, monitor(item))
        prefix = read(directory / 'prefix.json')
        record['prefix_stop'] = prefix.get('stop_reason')
        record['prefix_calls'] = len(prefix.get('turns', []))
        if record['status'] == 'admitted':
            admitted.add(item['family_id'])
        write_json(PROGRESS, progress)
        print(f'{number} {item["stratum"]} {record["status"]} {record["prefix_calls"]} calls', flush=True)
    return progress


def freeze_manifest(progress, candidates):
    if len(progress) != len(candidates) or any(item['status'] == 'screening' for item in progress.values()):
        raise RuntimeError('Expansion screening is incomplete.')
    tasks = []
    for item in progress.values():
        if item['status'] != 'admitted':
            continue
        prefix = read(ROOT / item['directory'] / 'prefix.json')
        offset = (item['queue_position'] - 1) % 3
        tasks.append({**item, 'context_sha256': prefix['context_sha256'], 'state': prefix['state'],
                      'order': list('ABC'[offset:] + 'ABC'[:offset] + 'D')})
    if len({item['family_id'] for item in tasks}) != len(tasks):
        raise RuntimeError('Duplicate admitted expansion family.')
    result = {'settings_sha256': sha(SETTINGS), 'tasks': tasks}
    write_json(MANIFEST, result)
    return result


def run_case(item):
    os.environ['IPYTHONDIR'] = str(RAW / f'worker-{os.getpid()}')
    row, evaluator = load_case(item['intervention_id'])
    directory = ROOT / item['directory']
    prefix = read(directory / 'prefix.json')
    if any(prefix.get(key) != item[key] for key in ('context_sha256', 'state')):
        raise RuntimeError('Expansion checkpoint metadata changed after freeze.')
    result = finish_case(row, evaluator, item, directory, monitor(item), (), order=item['order'])
    print(f'{item["intervention_id"]} {result}', flush=True)
    return result


def summarize(tasks):
    screened = read(PROGRESS)
    analyze.to_csv(RESULTS / 'screening_cases.csv', [
        {**candidate, 'decision': item['status'], 'prefix_stop': item.get('prefix_stop'),
         'prefix_calls': item.get('prefix_calls'), 'directory': item.get('directory')}
        for candidate in read(SETTINGS)['candidates']
        for item in [screened[str(candidate['intervention_id'])]]
    ])
    if not tasks:
        return
    costs, budget = analyze.cost_by_run()
    # The shared analysis looks up the retained-check count from its rule table.
    # The expansion uses the same scoring and has no additional retained labels.
    analyze.ANNOTATIONS = {**analyze.ANNOTATIONS, **{key: (rules, ()) for key, rules in RULES.items()}}
    rows = analyze.branch_rows(tasks, costs)
    analyze.to_csv(RESULTS / 'branch_metrics.csv', rows)
    analyze.to_csv(RESULTS / 'summary.csv', list(analyze.summaries(rows)))
    analyze.to_csv(RESULTS / 'paired.csv', list(analyze.paired(rows)))
    prefix = Counter()
    for key, usage in costs.items():
        if key.startswith('expansion_') and key.endswith('_prefix'):
            prefix.update(usage)
    write_json(RESULTS / 'budget.json', {'cumulative': budget, 'expansion_screening': dict(prefix)})
    print(f'Expansion cases {len(tasks)}, scored branches {sum(r["status"] == "scored" for r in rows)}',
          flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['preflight', 'freeze-settings', 'screen', 'run', 'all', 'summarize'])
    phase = parser.parse_args().phase
    RAW.mkdir(parents=True, exist_ok=True)
    with (RAW / 'expansion.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        current = design()
        candidates = current['candidates']
        if phase == 'preflight':
            preflight(candidates)
            return
        if phase == 'freeze-settings':
            if SETTINGS.exists():
                raise FileExistsError('Expansion settings already exist.')
            write_json(SETTINGS, current)
            print(json.dumps(Counter(item['stratum'] for item in candidates)), flush=True)
            return
        if read(SETTINGS) != current:
            raise RuntimeError('Expansion design differs from frozen settings.')
        if phase in {'screen', 'all'} and not MANIFEST.exists():
            progress = screen_all(candidates)
            if any(item['status'] == 'infrastructure_error' for item in progress.values()):
                progress = screen_all(candidates)
            freeze_manifest(progress, candidates)
        if phase == 'screen':
            return
        frozen = read(MANIFEST)
        if frozen.get('settings_sha256') != sha(SETTINGS):
            raise RuntimeError('Expansion manifest differs from frozen settings.')
        if phase in {'run', 'all'} and frozen['tasks']:
            with ProcessPoolExecutor(max_workers=formal.WORKERS) as pool:
                list(pool.map(run_case, frozen['tasks']))
        summarize(frozen['tasks'])


if __name__ == '__main__':
    main()
