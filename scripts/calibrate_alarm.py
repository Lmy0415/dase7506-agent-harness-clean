"""Run a scripted TargetSwap control in the local AppWorld simulator."""

import importlib.util
import json
import os
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / '.upstream' / 'InterventionBench'
TASK_ID = '31dc501_1'
INTERVENTION_ID = 386


def score(world, evaluate_revised, evaluation_code):
    from appworld import common, evaluator

    # Direct API calls skip the disk sync AppWorld.execute normally performs.
    world._save_state(world.output_db_home_path_on_disk)
    original = world.evaluate()
    # This AppWorld release binds the traceback helper in evaluator directly.
    with patch.object(common, 'errors', evaluator, create=True):
        revised, _ = evaluate_revised(world, evaluation_code)
    return {
        'original_passed': original.pass_count,
        'original_assertions': original.num_tests,
        'revised_passed': revised.pass_count,
        'revised_assertions': revised.num_tests,
        'revised_failures': revised.failures,
        'official_swap_pass': bool(revised.num_tests and revised.success and not original.success),
    }


def load_alarm_case():
    spec = importlib.util.spec_from_file_location(
        'interventionbench_assertions', UPSTREAM / 'scripts' / 'score_add_assertions.py'
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with (UPSTREAM / 'data' / 'appworld_interventions.jsonl').open() as source:
        row = next(row for row in map(json.loads, source) if row['intervention_idx'] == INTERVENTION_ID)
    if row['base_task_id'] != TASK_ID or row.get('skip') or row.get('_skipped'):
        raise ValueError('The calibration intervention does not match the pinned task.')
    return row, module.run_inline_evaluator


def login_to_simulated_phone(world):
    profile = world.apis.supervisor.show_profile()
    passwords = world.apis.supervisor.show_account_passwords()
    password = next(item['password'] for item in passwords if item['account_name'] == 'phone')
    return world.apis.phone.login(username=profile['phone_number'], password=password)['access_token']


def calibrate():
    os.environ['APPWORLD_ROOT'] = str(ROOT / '.appworld')
    from appworld import AppWorld

    row, evaluate_revised = load_alarm_case()
    with AppWorld(task_id=TASK_ID, experiment_name='clean_v3_alarm_calibration') as world:
        token = login_to_simulated_phone(world)
        alarms = world.apis.phone.show_alarms(access_token=token, page_limit=20)
        weekend = next(a['alarm_id'] for a in alarms if set(a['repeat_days'] or []) == {'saturday', 'sunday'})
        weekday = next(a['alarm_id'] for a in alarms if set(a['repeat_days'] or []) == {
            'monday', 'tuesday', 'wednesday', 'thursday', 'friday'
        })

        def snooze(alarm_id):
            return world.apis.phone.show_alarm(alarm_id=alarm_id, access_token=token)['snooze_minutes']

        def snapshot():
            return {'clock': datetime.now().isoformat(), 'weekday': snooze(weekday), 'weekend': snooze(weekend)}

        def update(alarm_id, minutes):
            before = snooze(alarm_id)
            response = world.requester._request(
                'phone', 'update_alarm', alarm_id=alarm_id, snooze_minutes=minutes, access_token=token
            )
            return {
                'tool': 'phone.update_alarm',
                'alarm_id': alarm_id,
                'requested_minutes': minutes,
                'http_status': response.status_code,
                'before': before,
                'after': snooze(alarm_id),
            }

        start = snapshot()
        checkpoint = world.save_state('before_pending_update')
        branches = {}
        for branch, writes in {
            'revised': [(weekend, 5)],
            'no_update': [],
            'weekday_then_undo': [(weekday, 5), (weekday, start['weekday']), (weekend, 5)],
        }.items():
            world.load_state(checkpoint)
            # load_state clears AppWorld's clock and does not reinstall it in this release.
            world._set_datetime()
            restored = snapshot()
            if restored != start:
                raise RuntimeError(f'Checkpoint mismatch for {branch}: {restored} != {start}')
            events = [update(alarm_id, minutes) for alarm_id, minutes in writes]
            world.apis.supervisor.complete_task(status='success')
            branches[branch] = {
                'events': events,
                'start': restored,
                'end': snapshot(),
                **score(world, evaluate_revised, row['evaluation_code']),
            }

    result = {
        'kind': 'scripted_calibration',
        'task_id': TASK_ID,
        'intervention_id': INTERVENTION_ID,
        'pending_request': {'tool': 'phone.update_alarm', 'alarm_id': weekday, 'snooze_minutes': 5},
        'branches': branches,
    }
    output = ROOT / 'artifacts' / 'raw' / 'alarm_calibration.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + '\n')
    if not branches['revised']['official_swap_pass'] or branches['no_update']['official_swap_pass']:
        raise RuntimeError(f'Positive/negative calibration failed. See {output}.')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    calibrate()
