"""Run the three PACT conditions from verified copies, with both budget ceilings."""

import argparse
import fcntl
import hashlib
import json
import os
import re
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from time import CLOCK_REALTIME, clock_gettime, sleep

from src import checkpoint, model
from src.analyze import cost_by_run
from src.batch import read
from src.env_adapter import Simulator, for_model
from src.model import ROOT
from src.pact import (ALL_TOOLS, ASSESS, COMMUNICATION, PROCEDURE, Controller, api_name,
                      boundary_receipt, communication, parse_assessment, receipt_notice, safe_read)
from src.pact_cases import MANIFEST, PROTOCOL, RAW
from src.runner import Run, SUFFIX_CALLS, OUTPUT_TOKENS, assistant_message, world_factory, write_json

LIMIT = 2_000_000_000
SETTINGS = PROTOCOL / 'pact_settings.json'
PILOT_SETTINGS = RAW / 'pilot_settings.json'
PROVIDER = RAW / 'provider.json'
HISTORICAL_FINGERPRINT = 'bc19ba97cbe016479903222bb1578db6'
RUN_FILES = ('src/pact.py', 'src/pact_runner.py', 'src/pact_cases.py', 'src/pact_score.py',
             'src/checkpoint.py', 'src/env_adapter.py', 'src/runner.py', 'src/model.py', 'src/monitor.py',
             'protocol/pact_selection.json', 'protocol/pact_manifest.json', 'protocol/pact_evaluation.json')
COMMON = COMMUNICATION + ' ' + (
    'After a goal change, use the public communication tools whenever useful. '
    'Use finish_session to end, or the original supervisor.complete_task if genuinely appropriate. '
    'The receipt reference supplied below refers to the last tool result before the new user message.'
)


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def occupation(records):
    amounts = {}
    scopes = {}
    statuses = {}
    for row in records:
        rid = row['request_id']
        if row['status'] == 'reserved':
            scopes[rid] = row['purpose'].startswith('pact_')
        if 'amount_nano_usd' in row:
            amounts[rid] = row['amount_nano_usd']
        statuses[rid] = row['status']
    project = sum(amounts.values())
    scope = sum(value for key, value in amounts.items() if scopes.get(key, False))
    outstanding = sum(value for key, value in amounts.items() if scopes.get(key, False)
                      and statuses[key] not in ('settled_peak_price', 'rejected'))
    return project, scope, outstanding


def reserve(request_id, purpose, max_tokens):
    # The project lock covers both checks and the reservation in one transaction.
    if not purpose.startswith('pact_'):
        raise RuntimeError('The PACT worker accepts only PACT purposes.')
    amount = model.CONTEXT_LIMIT * model.INPUT_CACHE_MISS + max_tokens * model.OUTPUT
    with model.locked_ledger() as fd:
        project, pact, _ = occupation(map(json.loads, fd))
        if project + amount > model.BUDGET or pact + amount > LIMIT:
            raise model.BudgetLimit('The project or PACT budget does not cover this reservation.')
        model.append_event(fd, request_id=request_id, purpose=purpose, status='reserved', amount_nano_usd=amount)


def provider_check(turn):
    seen = {'model': turn['model'], 'system_fingerprint': turn['system_fingerprint']}
    if seen['model'] != model.MODEL or not seen['system_fingerprint']:
        raise RuntimeError('The model receipt did not identify the requested DeepSeek Flash service.')
    with (RAW / 'provider.lock').open('a+') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        if PROVIDER.exists():
            if read(PROVIDER) != seen:
                raise RuntimeError('Provider changed within PACT. Stop before mixing service fingerprints.')
        else:
            write_json(PROVIDER, seen)


class PactRun(Run):
    def ask(self, messages, *, tools=None, json_output=False):
        for attempt in range(2):
            if self.result['attempted_calls'] == SUFFIX_CALLS:
                raise CallLimit()
            self.result['attempted_calls'] += 1
            self.flush()
            try:
                reply, turn = super().ask(messages, tools=tools, json_output=json_output)
                provider_check(turn)
                return reply, turn
            except model.TransientModelError as error:
                self.result['api_errors'].append({'attempted_call': self.result['attempted_calls'],
                                                  'error': type(error).__name__})
                self.flush()
                if attempt or self.result['attempted_calls'] == SUFFIX_CALLS:
                    raise
                sleep(2)
            except model.BudgetLimit:
                self.result['attempted_calls'] -= 1
                self.flush()
                raise


class CallLimit(RuntimeError):
    pass


def assessment(run, messages, update, catalogue):
    original = next(m['content'] for m in messages if m['role'] == 'user')
    visible_names = {
        app: [op for op in docs if not safe_read(f'{app}.{op}')]
        for app, docs in catalogue.items() if app != 'supervisor'
    }
    prompts = [*messages, {'role': 'user', 'content': ASSESS + '\nPublic write endpoint names: '
                           + json.dumps(visible_names, ensure_ascii=False, separators=(',', ':'))}]
    choices = []
    for attempt in range(2):
        reply, turn = run.ask(prompts, json_output=True)
        try:
            record = parse_assessment(reply.get('content') or '', update, original, catalogue)
        except (ValueError, TypeError) as error:
            record = {'old': 'unknown', 'basis': '', 'fix': '', 'cards': {}, 'issues': [str(error)[:180]]}
        choices.append(record)
        turn['pact_assessment'] = record
        run.flush()
        if not record['issues']:
            break
        if not attempt:
            prompts += [assistant_message(reply), {'role': 'user', 'content':
                'Correct these schema or evidence errors using only the visible messages: '
                + json.dumps(record['issues'][:5])}]
    result = max(choices, key=lambda x: (x['old'] != 'unknown', -len(x['issues']), len(x['cards'])))
    run.result['classification'] = result
    return result


def rejected(request, tool, reason):
    return {'request': request, 'tool': tool, 'http_status': 409,
            'response': {'error': reason, 'submitted': False},
            'submitted': False, 'complete': False}


def fingerprint_world(world):
    return checkpoint.state_signature(world)['model_hashes_sha256']


def invoke(simulator, controller, name, args, update, history):
    if name in ('report_conflict', 'request_decision', 'finish_session'):
        if (controller and name == 'finish_session' and args.get('status') == 'done' and
            (controller.selected() is not None or controller.boundary_state in ('WAIT_APPROVAL', 'UNKNOWN'))):
            return rejected(args, name, 'This session still has scheduled or unresolved work. Report waiting or partial accurately.')
        return communication(name, args)
    is_api = name == 'call_api'
    endpoint = api_name(args) if is_api else ''
    gate, selected = None, None
    if controller and is_api:
        allow, reason, selected = controller.gate(args, update, history)
        gate = {'decision': 'allow' if allow else 'reject', 'reason': reason,
                'selected': controller.selected(), 'goal_version': controller.version}
        controller.transition('dispatch' if allow else 'deny', endpoint=endpoint, **gate)
        if not allow:
            return {**rejected(args, name, reason + '. Follow the current scheduler and user scope.'),
                    'endpoint': endpoint, 'gate': gate}
    observer = None
    if is_api:
        observer = (lambda _: 'read') if safe_read(endpoint) else fingerprint_world
    event = simulator.invoke(name, args, observe=observer)
    event['tool'] = name
    event['submitted'] = 'before' in event
    event['effect_changed'] = bool(event['submitted'] and event['before'] != event['after'])
    if gate:
        event['gate'] = gate
        controller.after(selected, {'http_status': event['http_status'], 'response': event['response']}, endpoint)
    return event


def single_function(reply):
    functions = reply.get('tool_calls') or []
    if not functions:
        return None, None, None, None
    call = functions[0]
    fn = call['function']
    try:
        args = json.loads(fn['arguments'])
    except (ValueError, TypeError):
        args = None
    if len(functions) != 1 or not isinstance(args, dict):
        return call['id'], fn['name'], args, 'Use one documented tool call with a JSON object.'
    return call['id'], fn['name'], args, None


def execute(run, saved, update, simulator, method):
    receipt, committed, body = boundary_receipt(saved['history'])
    messages = list(saved['history'])
    messages[0] = {'role': 'system', 'content': messages[0]['content'] + '\n' + COMMON}
    instruction = receipt_notice(receipt)
    if method != 'A':
        instruction += '\n' + PROCEDURE
    messages += [{'role': 'assistant', 'content': instruction}, {'role': 'user', 'content': update}]
    run.result['boundary_receipt'] = receipt['id']
    controller = None
    if method == 'PACT':
        view = assessment(run, messages, update, simulator.catalogue)
        controller = Controller(view, receipt, committed, body, simulator.catalogue)
        run.result['control'] = controller.records
        run.result['automatic_events'] = controller.messages_to_user()
        for event in run.result['automatic_events']:
            messages.append({'role': 'assistant', 'content': 'The controller delivered a simulated user message: '
                             + json.dumps({'tool': event['tool'], 'message': event['request']} )})
        run.flush()
    while run.result['attempted_calls'] < SUFFIX_CALLS:
        context = [*messages, {'role': 'assistant', 'content': controller.prompt()}] if controller else messages
        reply, turn = run.ask(context, tools=ALL_TOOLS)
        cid, tool, args, error = single_function(reply)
        if cid is None:
            return 'stopped_without_tool'
        messages.append(assistant_message(reply))
        if error:
            event = {**rejected(args, tool, error), 'http_status': 400}
            calls = reply['tool_calls']
            for call in calls:
                messages.append({'role': 'tool', 'tool_call_id': call['id'], 'content': for_model(event)})
        else:
            event = invoke(simulator, controller, tool, args, update, messages)
            messages.append({'role': 'tool', 'tool_call_id': cid, 'content': for_model(event)})
        turn['events'] = [event]
        if controller:
            run.result['final_task_states'] = {'boundary': controller.boundary_state, 'tasks': controller.status()}
        run.flush()
        if event.get('complete'):
            return 'session_finish' if tool == 'finish_session' else 'simulator_finish'
    return 'budgeted_model_call_limit'


def run_branch(item, boundary, method):
    stage, n = item['stage'], item['intervention_id']
    path = RAW / stage / f'case_{n}' / boundary / f'{method}.json'
    prior = read(path)
    if prior:
        if prior.get('status') == 'terminal' and prior.get('terminal_saved'):
            return 'skipped'
        raise RuntimeError(f'Preserved incomplete branch {n}/{boundary}/{method}; no automatic replay.')
    run_phase = 'pilot2' if stage == 'pilot' else stage
    run_id = f'pact_{run_phase}_{n}_{boundary}_{method}'
    trace = {'run_id': run_id, 'stage': stage, 'intervention_id': n, 'family_id': item['family_id'],
             'task_id': item['task_id'], 'boundary': boundary, 'method': method, 'turns': [],
             'attempted_calls': 0, 'api_errors': [], 'status': 'started',
             'update_sha256': checkpoint.digest(item['update'])}
    run = PactRun(trace, path)
    run.flush()
    frozen = item['boundary'][boundary]
    with world_factory(item['task_id'], run_id) as world:
        saved = checkpoint.restore(world, ROOT / frozen['path'])
        trace['start'] = {k: saved[k] for k in ('state', 'context_sha256', 'db_hashes', 'adapter_state_sha256')}
        assert trace['start'] == {k: frozen[k] for k in trace['start']}
        simulator = Simulator(world, saved['adapter_state'])
        try:
            trace['stop_reason'] = execute(run, saved, item['update'], simulator, method)
        except CallLimit:
            trace['stop_reason'] = 'budgeted_model_call_limit'
        except (model.BudgetLimit, model.TransientModelError) as error:
            trace['stop_reason'] = 'hard_budget_stopped' if isinstance(error, model.BudgetLimit) else 'api_retry_exhausted'
            trace['infrastructure_error'] = type(error).__name__
        finally:
            world._save_state(world.output_db_home_path_on_disk)
            trace['terminal_saved'] = True
            trace['status'] = 'terminal'
            trace['stop_reason'] = trace.get('stop_reason', 'infrastructure_failure')
            run.flush()
    return trace['stop_reason']


def work(item):
    model.reserve = reserve
    os.environ['IPYTHONDIR'] = str(RAW / f'worker-{os.getpid()}')
    n = item['intervention_id']
    states = {}
    for boundary, order in item['method_order'].items():
        for method in order:
            states[boundary + '_' + method] = run_branch(item, boundary, method)
            if states[boundary + '_' + method] == 'hard_budget_stopped':
                print(n, states, flush=True)
                return True
    print(n, states, flush=True)
    return False


def design():
    return {'model_alias': model.MODEL, 'published_version': 'DeepSeek-V4.1-Flash-1017',
            'previous_fingerprint': HISTORICAL_FINGERPRINT, 'thinking': 'disabled',
            'calls_per_branch_including_assessment_and_retry': SUFFIX_CALLS, 'max_output_tokens': OUTPUT_TOKENS,
            'max_repairs': 1, 'transient_retry': 'one per failed logical request, charged to branch limit',
            'worker_processes': 2, 'budget_project_nano_usd': model.BUDGET, 'budget_pact_nano_usd': LIMIT,
            'prompts': {'common': COMMON, 'procedure': PROCEDURE, 'assessment': ASSESS},
            'tools': ALL_TOOLS, 'source_sha256': {f: file_hash(ROOT / f) for f in RUN_FILES}}


def freeze():
    if SETTINGS.exists():
        raise FileExistsError('Formal settings already frozen.')
    pilot = [i for i in read(MANIFEST)['tasks'] if i['stage'] == 'pilot']
    current = design()
    first = read(PILOT_SETTINGS)
    if len(pilot) not in (2, 3) or not first:
        raise ValueError('Expected a recorded pilot of two or three separate task families.')
    if first != current:
        raise ValueError('Analyzed pilot code does not match the setting to freeze.')
    grades = [read(RAW / 'pilot' / f"case_{i['intervention_id']}" / b / f'{m}.score.json')
              for i in pilot for b, order in i['method_order'].items() for m in order]
    assert all('arr' in grade for grade in grades)
    assert read(RAW / 'component_control.json').get('passed') is True
    with model.locked_ledger() as handle:
        project, pact, outstanding = occupation(map(json.loads, handle))
    formal = [i for i in read(MANIFEST)['tasks'] if i['stage'] == 'formal']
    if len(formal) < 8:
        raise ValueError('Fewer than eight strict matched task families. Report only mechanism controls.')
    # Twice the pilot per-family amount plus two simultaneous worst-case reservations.
    actual, _ = cost_by_run()
    confirmation = sum(cost['peak_nano_usd'] for run, cost in actual.items() if run.startswith('pact_pilot2_'))
    if not confirmation:
        raise ValueError('The confirmation pilot has no metered calls.')
    estimate = (2 * confirmation * len(formal) + len(pilot) - 1) // len(pilot)
    buffer = 2 * (model.CONTEXT_LIMIT * model.INPUT_CACHE_MISS + OUTPUT_TOKENS * model.OUTPUT)
    if pact + estimate + buffer > LIMIT or project + estimate + buffer > model.BUDGET:
        raise model.BudgetLimit('The pilot-based conservative estimate does not fit.')
    write_json(SETTINGS, {**current, 'provider_receipt': read(PROVIDER), 'frozen_at_unix': clock_gettime(CLOCK_REALTIME),
                          'project_cost_at_freeze': project, 'pact_cost_at_freeze': pact,
                          'pact_outstanding_at_freeze': outstanding, 'formal_projection_nano_usd': estimate,
                          'parallel_reservation_buffer_nano_usd': buffer,
                          'primary': 'ARR over every frozen branch, family-matched PACT minus P and A',
                          'component_control_sha256': file_hash(RAW / 'component_control.json'),
                          'single_pilot_revision': 'De-duplicate the boundary operation and its exact inverse. '
                          'Compare serialized records as lists; allow optional report details when identity fields match.'})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('pilot', 'freeze', 'formal'))
    stage = parser.parse_args().phase
    if not MANIFEST.exists():
        raise RuntimeError('Checked matched scenarios are required before running.')
    os.environ.setdefault('IPYTHONDIR', str(RAW / 'ipython'))
    with (RAW / 'batch.lock').open('a+') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if stage == 'freeze':
            freeze()
            return
        config = design()
        if stage == 'pilot':
            if not read(RAW / 'component_control.json').get('passed'):
                raise ValueError('Real AppWorld component control must pass first.')
            if PILOT_SETTINGS.exists() and read(PILOT_SETTINGS) != config:
                raise RuntimeError('The pilot settings differ. Preserve the original trial before revising.')
            if not PILOT_SETTINGS.exists():
                write_json(PILOT_SETTINGS, config)
        elif any(read(SETTINGS).get(k) != v for k, v in config.items()):
            raise ValueError('Formal settings are missing or have drifted.')
        tasks = [i for i in read(MANIFEST)['tasks'] if i['stage'] == stage]
        with ProcessPoolExecutor(max_workers=2) as pool:
            for i in range(0, len(tasks), 2):
                results = list(pool.map(work, tasks[i:i + 2]))
                if any(results):
                    break


if __name__ == '__main__':
    main()
