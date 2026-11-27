"""Evaluate R, C+, and C++ from frozen AppWorld checkpoints."""

import argparse
import fcntl
import json
import os
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from scripts.calibrate_alarm import load_case
from src import checkpoint, expansion, formal
from src.annotations import ANNOTATIONS
from src.batch import read, resume_attempt
from src.env_adapter import Simulator
from src.intent_guard import decision, supported_signature
from src.intent_revision import (
    INTENT_PROMPT, R_PROMPT, intent_state, receipt_index, revised_goal, visible_receipts,
)
from src.model import ROOT, BudgetLimit
from src.monitor import Monitor
from src.runner import (
    OUTPUT_TOKENS, REPAIR, SUFFIX_CALLS, Run, branch_result, branch_score, execute,
    prepare_plan, world_factory, write_json,
)

RAW = ROOT / 'artifacts' / 'raw' / 'harness_v4'
SETTINGS = ROOT / 'protocol' / 'harness_v4_settings.json'
MANIFEST = ROOT / 'protocol' / 'harness_v4_manifest.json'
ARMS = ('R', 'C+', 'C++')
SOURCE_FILES = (
    formal.SETTINGS, formal.MANIFEST, expansion.SETTINGS, expansion.MANIFEST,
    Path(__file__), ROOT / 'src' / 'intent_revision.py', ROOT / 'src' / 'intent_guard.py',
)


class ProviderChanged(RuntimeError):
    pass


class RevisionRun(Run):
    def __init__(self, result, path, fingerprint):
        super().__init__(result, path)
        self.fingerprint = fingerprint
        self.state = None

    def ask(self, messages, *, tools=None, json_output=False):
        if self.state is not None:
            self.state['execution'] = visible_receipts(messages)
            remaining = [step for step in self.state['plan'] if step['status'] not in ('done', 'cancelled')]
            summary = {
                'intent': self.state['intent'], 'remaining_plan': remaining,
                'recent_receipts': receipt_index(self.state['execution'], tail=6),
            }
            messages = [*messages, {'role': 'assistant', 'content': (
                'Current working state. Follow the latest user instruction. A request being accepted does '
                'not by itself establish task completion. ' + json.dumps(summary, ensure_ascii=False)
            )}]
        response, turn = super().ask(messages, tools=tools, json_output=json_output)
        if turn['model'] != formal.MODEL or turn.get('system_fingerprint') != self.fingerprint:
            raise ProviderChanged('The returned model or serving fingerprint differs from the original run.')
        return response, turn


class GuardedSimulator(Simulator):
    def __init__(self, world, tokens, signature, decisions):
        super().__init__(world, tokens)
        self.signature = signature
        self.decisions = decisions

    def invoke(self, name, args, observe=None):
        outcome = decision(name, args, self.signature)
        self.decisions.append({'decision': outcome, 'tool': name, 'request': args,
                               'signature': self.signature if outcome == 'block' else None,
                               'submitted': False if outcome == 'block' else None})
        if outcome == 'block':
            return {'request': args, 'http_status': 409, 'complete': False, 'response': {
                'blocked': True, 'reason': 'Conflicts with a revoked user requirement. Choose another action.',
            }}
        event = super().invoke(name, args, observe=observe)
        self.decisions[-1]['submitted'] = 'before' in event
        return event


def continue_agent(run, restore, update, world, monitor):
    messages = [*restore['history'], {'role': 'user', 'content': update}]
    strategy = run.result['strategy']
    if strategy == 'R':
        goal = prepare_plan(messages, run, R_PROMPT, revised_goal)
        run.result['consolidated_goal'] = goal
        run.result['fallback'] = goal is None
        if goal is not None:
            messages.append({'role': 'assistant', 'content': 'Current effective user instruction: ' + goal})
    else:
        ledger = visible_receipts(restore['history'])
        evidence = [entry for entry in ledger if entry['api'] != 'find_api'
                    and entry['status'] in ('request_accepted', 'partial_response')]
        instruction = INTENT_PROMPT + '\nCompleted-call index: ' + json.dumps(receipt_index(evidence), ensure_ascii=False)
        parser = lambda text: intent_state(text, restore['old_plan'], ledger)
        run.state = prepare_plan(messages, run, instruction, parser)
        run.result['fallback'] = run.state is None
        run.result['state_at_revision'] = dict(run.state) if run.state is not None else None
    if strategy == 'C++':
        outcomes = run.result['guard_decisions'] = []
        signature = supported_signature(run.state, update)
        run.result['guard_signature'] = signature
        simulator = GuardedSimulator(world, restore['adapter_state'], signature, outcomes)
    else:
        simulator = Simulator(world, restore['adapter_state'])
    stop, _ = execute(messages, simulator, run, monitor, SUFFIX_CALLS - len(run.result['turns']))
    if run.state is not None:
        run.result['execution_at_end'] = visible_receipts(messages)
    return stop


def rules_for(item):
    if item.get('cohort') == 'expansion':
        return expansion.monitor(item), ()
    rules, retained = ANNOTATIONS[item['intervention_id']]
    return Monitor(rules), retained


def run_branch(item, arm, path, fingerprint):
    number = item['intervention_id']
    row, evaluator = load_case(number)
    source = ROOT / item['directory']
    result = branch_result(row, f'{path.parent.parent.name}_{number}_{arm}', arm)
    run = RevisionRun(result, path, fingerprint)
    result['status'] = 'started'
    run.flush()
    try:
        with world_factory(item['task_id'], result['run_id']) as world:
            monitor, retained = rules_for(item)
            monitor = monitor.bind(world)
            restored = checkpoint.restore(world, source / 'checkpoint')
            if any(restored[key] != item[key] for key in ('state', 'context_sha256')):
                raise RuntimeError('Restored checkpoint metadata differs from the frozen case.')
            result['state'] = restored['state']
            result['context_sha256'] = restored['context_sha256']
            result['stop_reason'] = continue_agent(run, restored, row['intervention_text'], world, monitor)
            result['score'] = branch_score(world, row, evaluator, result, retained)
    except Exception as error:
        result['infrastructure_error'] = type(error).__name__
        raise
    finally:
        result['status'] = 'terminal'
        run.flush()


def pilot_cases():
    selected = []
    for item in read(formal.PILOT / 'progress.json').values():
        if item['status'] != 'admitted':
            continue
        path = Path(item['directory'])
        prefix = read(path / 'prefix.json')
        selected.append({**item, 'directory': str(path.resolve().relative_to(ROOT)),
                         'context_sha256': prefix['context_sha256'], 'state': prefix['state'],
                         'cohort': 'pilot'})
    counts = Counter(item['stratum'] for item in selected)
    if not (6 <= len(selected) <= 8 and counts['Drop'] >= 2):
        raise RuntimeError('The verified eight-family pilot pool is unavailable.')
    return selected


def formal_cases():
    tasks = [{**item, 'cohort': cohort}
             for cohort, path in [('original', formal.MANIFEST), ('expansion', expansion.MANIFEST)]
             for item in read(path)['tasks']]
    if len({item['family_id'] for item in tasks}) != len(tasks):
        raise RuntimeError('Frozen cohorts overlap.')
    return tasks


def scheduled(tasks):
    return [{**item, 'v4_order': list(ARMS[index % len(ARMS):] + ARMS[:index % len(ARMS)])}
            for index, item in enumerate(tasks)]


def design():
    original = formal.settings()
    if read(expansion.SETTINGS) != expansion.design():
        raise RuntimeError('The expansion settings no longer match their frozen design.')
    settled, reserved, _, _ = formal.ledger_summary()
    labels = {(v['model'], v['system_fingerprint']) for key, v in settled.items()
              if not reserved[key]['purpose'].startswith(('expansion_', 'v4_'))}
    if len(labels) != 1 or next(iter(labels))[0] != formal.MODEL:
        raise RuntimeError('Could not identify the original serving fingerprint.')
    return {
        'provider_model': formal.MODEL,
        'provider_version': original['provider_version_at_verification'],
        'system_fingerprint': next(iter(labels))[1],
        'max_calls_per_branch': SUFFIX_CALLS,
        'max_output_tokens': OUTPUT_TOKENS,
        'max_format_repairs': 1,
        'fallback': 'native continuation',
        'arms': list(ARMS),
        'prompts': {'R': R_PROMPT, 'C+ and C++': INTENT_PROMPT, 'repair': REPAIR},
        'model_thinking': 'disabled',
        'worker_processes': formal.WORKERS,
        'cohort': 'All original and expansion checkpoints. Exploratory post-hoc comparison.',
        'source_sha256': {str(path.relative_to(ROOT)): expansion.sha(path) for path in SOURCE_FILES},
    }


def run_case(work):
    item, phase, fingerprint = work
    os.environ['IPYTHONDIR'] = str(RAW / f'worker-{os.getpid()}')
    number = item['intervention_id']
    statuses = {}
    for arm in item['v4_order']:
        path = RAW / phase / f'case_{number}' / f'{arm}.json'
        prior = read(path)
        if prior.get('infrastructure_error') == 'ProviderChanged':
            raise ProviderChanged('Prior receipt records a provider change.')
        if prior.get('score') is None and resume_attempt(path):
            try:
                run_branch(item, arm, path, fingerprint)
            except (BudgetLimit, ProviderChanged):
                raise
            except Exception as error:
                print(f'{phase} {number} {arm}: {type(error).__name__}; trace retained', flush=True)
        outcome = read(path)
        statuses[arm] = 'scored' if outcome.get('score') is not None else 'incomplete'
    print(f'{phase} {number} {item["stratum"]} {statuses}', flush=True)
    return statuses


def batch(phase, tasks, fingerprint):
    with ProcessPoolExecutor(max_workers=formal.WORKERS) as pool:
        for start in range(0, len(tasks), formal.WORKERS):
            wave = tasks[start:start + formal.WORKERS]
            list(pool.map(run_case, [(item, phase, fingerprint) for item in wave]))


def pilot_phase(arm):
    return 'v4_pilot' if arm == 'R' else 'v4_confirmation'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['pilot', 'confirm', 'freeze', 'formal'])
    phase = parser.parse_args().phase
    RAW.mkdir(parents=True, exist_ok=True)
    with (RAW / 'harness_v4.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        current = design()
        if phase in ('pilot', 'confirm'):
            confirm = phase == 'confirm'
            settings = RAW / ('confirmation_settings.json' if confirm else 'pilot_settings.json')
            if confirm and not (RAW / 'pilot_settings.json').is_file():
                raise RuntimeError('Preserve the original pilot before its confirmation.')
            if settings.exists() and read(settings) != current:
                raise RuntimeError('The pilot design changed. Keep prior outputs and freeze a confirmation batch.')
            if not settings.exists():
                write_json(settings, current)
            tasks = scheduled(pilot_cases())
            if confirm:
                tasks = [{**item, 'v4_order': [arm for arm in item['v4_order'] if arm != 'R']} for item in tasks]
            batch('v4_confirmation' if confirm else 'v4_pilot', tasks, current['system_fingerprint'])
        elif phase == 'freeze':
            if SETTINGS.exists() or MANIFEST.exists():
                raise FileExistsError('The V4 design has already been frozen.')
            if read(RAW / 'confirmation_settings.json') != current:
                raise RuntimeError('Require a confirmation under the proposed frozen design.')
            cases = scheduled(pilot_cases())
            traces = {(item['stratum'], arm): [
                read(RAW / pilot_phase(arm) / f"case_{candidate['intervention_id']}" / f'{arm}.json')
                for candidate in cases if candidate['stratum'] == item['stratum']
            ] for item in cases for arm in ARMS}
            if any(len(entries) < 2 or not all(trace.get('score') is not None for trace in entries)
                   or not any(trace.get('fallback') is False for trace in entries)
                   for entries in traces.values()):
                raise RuntimeError('Pilot does not meet scored and structured-output requirements for both strata.')
            write_json(SETTINGS, {**current, 'frozen_at_utc': datetime.now(timezone.utc).isoformat()})
            write_json(MANIFEST, {'settings_sha256': expansion.sha(SETTINGS), 'exclusions': [],
                                  'tasks': scheduled(formal_cases())})
        else:
            saved = read(SETTINGS)
            manifest = read(MANIFEST)
            if any(saved.get(key) != val for key, val in current.items()) or (
                manifest.get('settings_sha256') != expansion.sha(SETTINGS)
            ):
                raise RuntimeError('The formal run does not match frozen V4 settings.')
            batch('v4_formal', manifest['tasks'], saved['system_fingerprint'])


if __name__ == '__main__':
    main()
