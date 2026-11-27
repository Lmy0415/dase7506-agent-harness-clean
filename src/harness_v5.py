"""Pilot and frozen V5 continuations with a shared C5/G5 revision."""

import argparse
import fcntl
import json
import os
from copy import deepcopy
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from scripts.calibrate_alarm import load_case
from src import checkpoint, expansion, formal, harness_v4
from src.batch import read, resume_attempt
from src.env_adapter import Simulator
from src.guard_v5 import evaluate, guard_rule
from src.intent_revision import receipt_index, visible_receipts
from src.intent_v5 import C5_PROMPT, inspect_state
from src.model import BudgetLimit
from src.runner import (
    SUFFIX_CALLS, assistant_message, branch_result, branch_score, execute, world_factory, write_json,
)

ROOT = formal.ROOT
RAW = ROOT / 'artifacts/raw/harness_v5'
RESULTS = ROOT / 'results/harness_v5'
COMPONENTS = ROOT / 'protocol/harness_v5_components.json'
SETTINGS = ROOT / 'protocol/harness_v5_settings.json'
MANIFEST = ROOT / 'protocol/harness_v5_manifest.json'
REPAIR = (
    'Return the same five-field object. Fix only the invalid fields below; keep valid information. '
    'Never claim done without matching visible evidence. You may omit unreliable evidence.'
)


class GuardedSimulator(Simulator):
    def __init__(self, world, tokens, rule, checks):
        super().__init__(world, tokens)
        self.rule = rule
        self.checks = checks

    def invoke(self, name, args, observe=None):
        decision, basis = evaluate(name, args, self.rule)
        record = {'decision': decision, 'basis': basis, 'tool': name, 'request': args, 'submitted': False}
        self.checks.append(record)
        if decision == 'block':
            return {'request': args, 'http_status': 409, 'complete': False, 'response': {
                'blocked': True, 'reason': 'This specific request conflicts with the latest user withdrawal.',
            }}
        event = super().invoke(name, args, observe=observe)
        record['submitted'] = 'before' in event
        record['http_status'] = event['http_status']
        return event


def preparation(item, row, saved, path, fingerprint):
    previous = read(path)
    if previous.get('report') is not None and not previous.get('infrastructure_error'):
        if previous['context_sha256'] != saved['context_sha256']:
            raise RuntimeError('Shared revision checkpoint differs from the saved source.')
        return previous
    if previous.get('infrastructure_error') == 'ProviderChanged':
        raise harness_v4.ProviderChanged('The recorded provider changed.')
    if not resume_attempt(path):
        raise RuntimeError('Shared revision is terminal and cannot be resumed.')

    result = branch_result(row, f'{path.parent.parent.name}_{item["intervention_id"]}_shared', 'shared')
    result['context_sha256'] = saved['context_sha256']
    result['status'] = 'started'
    run = harness_v4.RevisionRun(result, path, fingerprint)
    run.flush()
    try:
        ledger = visible_receipts(saved['history'])
        submitted = [r for r in ledger if r['api'] != 'find_api'
                     and r['status'] in ('request_accepted', 'partial_response')]
        visible_index = receipt_index(submitted)
        messages = [*saved['history'], {'role': 'user', 'content': row['intervention_text']}]
        prompts = [*messages, {'role': 'user', 'content': C5_PROMPT + '\nCompleted-call index: '
                    + json.dumps(visible_index, ensure_ascii=False)}]
        reports = []
        for attempt in range(2):
            response, turn = run.ask(prompts, json_output=True)
            report = inspect_state(response.get('content') or '', saved['old_plan'], ledger)
            reports.append(report)
            turn['component_report'] = {k: v for k, v in report.items() if k != 'state'}
            if report['mode'] == 'full':
                break
            if not attempt:
                issue_list = json.dumps(report['issues'][:8], ensure_ascii=False)
                info = f'\nProblems: {issue_list}\nValid steps: {[s["id"] for s in saved["old_plan"]]}. '
                info += f'Offered receipt IDs: {[e["id"] for e in visible_index]}.'
                prompts += [assistant_message(response), {'role': 'user', 'content': REPAIR + info}]

        def quality(r):
            return (('fallback', 'partial', 'full').index(r['mode']), sum(r['modules'].values()),
                    -len(r['issues']))

        index = max(range(len(reports)), key=lambda k: quality(reports[k]))
        result['report'] = reports[index]
        result['chosen_attempt'] = index + 1
        return result
    except Exception as error:
        result['infrastructure_error'] = type(error).__name__
        raise
    finally:
        result['status'] = 'terminal'
        run.flush()


def run_branch(item, row, scorer, arm, revision, path, fingerprint):
    saved_path = ROOT / item['directory'] / 'checkpoint'
    result = branch_result(row, f'{path.parent.parent.name}_{item["intervention_id"]}_{arm}', arm)
    result.update({'status': 'started', 'shared_calls': len(revision['turns']),
                   'shared_revision_id': revision['run_id'], 'state_mode': revision['report']['mode'],
                   'chosen_attempt': revision['chosen_attempt'],
                   'components': {k: v for k, v in revision['report'].items() if k != 'state'}})
    run = harness_v4.RevisionRun(result, path, fingerprint)
    run.flush()
    try:
        with world_factory(item['task_id'], result['run_id']) as world:
            if item.get('cohort') == 'v5_new':
                from src.v5_sampling import monitor
                rule_monitor, retained = monitor(item), ()
            else:
                rule_monitor, retained = harness_v4.rules_for(item)
            rule_monitor = rule_monitor.bind(world)
            saved = checkpoint.restore(world, saved_path)
            if any(saved[key] != item[key] for key in ('state', 'context_sha256')):
                raise RuntimeError('V5 branch cannot restore the frozen checkpoint.')
            run.state = deepcopy(revision['report']['state'])
            result['state'] = saved['state']
            result['context_sha256'] = saved['context_sha256']
            messages = [*saved['history'], {'role': 'user', 'content': row['intervention_text']}]
            if arm == 'G5':
                intent = run.state['intent'] if run.state and revision['report']['modules']['intent'] else None
                rule, reason = guard_rule(intent, visible_receipts(saved['history']), row['intervention_text'])
                checks = []
                result['guard'] = {'rule': rule, 'readiness': reason, 'checks': checks, 'model_calls': 0}
                sim = GuardedSimulator(world, saved['adapter_state'], rule, checks)
            else:
                sim = Simulator(world, saved['adapter_state'])
            stop, _ = execute(messages, sim, run, rule_monitor, SUFFIX_CALLS - result['shared_calls'])
            result['stop_reason'] = stop
            result['score'] = branch_score(world, row, scorer, result, retained)
            if arm == 'G5':
                checks = result['guard']['checks']
                positions = [i for i, x in enumerate(checks) if x['decision'] == 'block']
                result['guard']['recovered_after_block'] = bool(
                    positions and result['score']['revised_final_success']
                    and any(c['submitted'] and 200 <= c.get('http_status', 0) < 300 for c in checks[positions[-1] + 1:])
                )
    except Exception as error:
        result['infrastructure_error'] = type(error).__name__
        raise
    finally:
        result['status'] = 'terminal'
        run.flush()


def run_case(work):
    item, phase, fingerprint = work
    n = item['intervention_id']
    os.environ['IPYTHONDIR'] = str(RAW / f'worker-{os.getpid()}')
    directory = RAW / phase / f'case_{n}'
    row, scorer = load_case(n)
    saved = read(ROOT / item['directory'] / 'checkpoint/manifest.json')
    assert saved['context_sha256'] == item['context_sha256'] == checkpoint.digest(
        [saved[key] for key in ('history', 'old_plan', 'pending')]
    )
    revision = preparation(item, row, saved, directory / 'revision.json', fingerprint)
    status = {}
    for arm in item['v5_order']:
        path = directory / f'{arm}.json'
        previous = read(path)
        if previous.get('infrastructure_error') == 'ProviderChanged':
            raise harness_v4.ProviderChanged('The recorded provider changed.')
        if previous.get('score') is None and resume_attempt(path):
            try:
                run_branch(item, row, scorer, arm, revision, path, fingerprint)
            except (BudgetLimit, harness_v4.ProviderChanged):
                raise
            except Exception as error:
                print(f'{phase} {n} {arm}: {type(error).__name__}; trace preserved.', flush=True)
        status[arm] = 'scored' if read(path).get('score') is not None else 'incomplete'
    print(f'{phase} {n} {item["stratum"]} {revision["report"]["mode"]} {status}', flush=True)
    return status


def schedule(tasks, arms):
    return [{**item, 'v5_order': list(arms[i % len(arms):] + arms[:i % len(arms)])}
            for i, item in enumerate(tasks)]


def batch(tasks, phase, fingerprint):
    with ProcessPoolExecutor(max_workers=2) as pool:
        for start in range(0, len(tasks), 2):
            list(pool.map(run_case, [(item, phase, fingerprint) for item in tasks[start:start + 2]]))


def component_gate():
    import csv

    controls = list(csv.DictReader((RESULTS / 'guard_offline_metrics.csv').open()))
    rows = {(r['dataset'], r['scope']): r for r in controls if r['policy'] == 'v5'}
    pilot = rows['pilot_control', 'application']
    scripted = rows['synthetic_control', 'all']
    evidence = read(RESULTS / 'guard_simulator_control.json')
    return (int(pilot['tp']) >= 1 and int(pilot['fp']) == 0 and int(pilot['tn']) >= 1
            and int(scripted['fp']) == 0 and int(scripted['tn']) >= 1 and int(scripted['unverified_blocks']) == 0
            and evidence.get('blocked') is True and evidence.get('unchanged') is True
            and evidence.get('continued') is True)


def settings():
    v4 = read(harness_v4.SETTINGS)
    components = read(COMPONENTS)
    if any(expansion.sha(ROOT / name) != expected for name, expected in components['source_sha256'].items()):
        raise RuntimeError('Offline component hashes changed.')
    files = [Path(__file__), COMPONENTS, harness_v4.SETTINGS, harness_v4.MANIFEST,
             ROOT / 'DASE7506_Harness_V5_Final_Experiment.md']
    return {
        'provider_model': v4['provider_model'], 'provider_version': v4['provider_version'],
        'system_fingerprint': v4['system_fingerprint'], 'thinking': v4['model_thinking'],
        'calls_per_suffix': SUFFIX_CALLS, 'output_tokens_per_call': v4['max_output_tokens'],
        'max_repairs': 1, 'revision_prompt': C5_PROMPT, 'repair_prompt': REPAIR,
        'shared_revision': True, 'guard_model_calls': 0,
        'primary': ['C5-C+', 'C5-C', 'C5-A', 'G5-C5'],
        'stratum': ['Swap', 'Drop'], 'bootstrap_repeats': 10000, 'bootstrap_seed': 7506,
        'source_sha256': {str(path.relative_to(ROOT)): expansion.sha(path) for path in files},
    }


def pilot_ok(tasks, phase, arms):
    usable = []
    for item in tasks:
        root = RAW / phase / f'case_{item["intervention_id"]}'
        revision = read(root / 'revision.json')
        if any(read(root / f'{arm}.json').get('score') is None for arm in arms):
            return False
        if revision['report']['mode'] in ('full', 'partial'):
            usable.append(item)
    return len(usable) >= (len(tasks) // 2 + 1) and {r['stratum'] for r in usable} == {'Swap', 'Drop'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['pilot', 'freeze', 'formal'])
    args = parser.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)
    with (RAW / 'runner.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        design = settings()
        phase = 'v5_pilot'
        pilot = harness_v4.pilot_cases()
        if args.phase == 'pilot':
            arms = ('C5', 'G5') if component_gate() else ('C5',)
            frozen = {'settings': design, 'arms': list(arms), 'cases': schedule(pilot, arms)}
            path = RAW / 'pilot_settings.json'
            if path.exists() and read(path) != frozen:
                raise RuntimeError('Pilot design does not match the recorded run.')
            if not path.exists():
                write_json(path, frozen)
            batch(frozen['cases'], phase, design['system_fingerprint'])
        elif args.phase == 'freeze':
            if SETTINGS.exists() or MANIFEST.exists():
                raise FileExistsError('The formal V5 design is already frozen.')
            prior = read(RAW / 'pilot_settings.json')
            if prior.get('settings') != design or not pilot_ok(pilot, phase, ('C5',)):
                raise RuntimeError('C5 requires a usable pilot in both strata.')
            g5 = 'G5' in prior['arms'] and component_gate() and pilot_ok(pilot, phase, ('C5', 'G5'))
            arms = ('C5', 'G5') if g5 else ('C5',)
            write_json(SETTINGS, {**design, 'arms': list(arms), 'guard_component_gate': g5,
                                  'frozen_at_utc': datetime.now(timezone.utc).isoformat()})
            write_json(MANIFEST, {'settings_sha256': expansion.sha(SETTINGS), 'cohort': 'historical_40_exploratory',
                                  'tasks': schedule(read(harness_v4.MANIFEST)['tasks'], arms)})
        else:
            frozen = read(SETTINGS)
            manifest = read(MANIFEST)
            if (any(frozen.get(key) != value for key, value in design.items())
                    or manifest['settings_sha256'] != expansion.sha(SETTINGS)):
                raise RuntimeError('V5 formal configuration does not match the frozen design.')
            batch(manifest['tasks'], 'v5_formal', design['system_fingerprint'])


if __name__ == '__main__':
    main()
