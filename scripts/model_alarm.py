"""Run one independent model smoke test in the official AppWorld simulator."""

import json
import os
from uuid import uuid4

from scripts.calibrate_alarm import ROOT, TASK_ID, load_alarm_case, login_to_simulated_phone, score
from src.model import complete

TOOLS = [
    {
        'type': 'function',
        'function': {
            'name': 'show_alarms', 'description': 'List the alarms on the simulated phone.',
            'parameters': {'type': 'object', 'properties': {}, 'additionalProperties': False},
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'update_alarm_snooze', 'description': 'Set the snooze minutes for an alarm.',
            'parameters': {
                'type': 'object', 'additionalProperties': False,
                'properties': {'alarm_id': {'type': 'integer'}, 'snooze_minutes': {'type': 'integer'}},
                'required': ['alarm_id', 'snooze_minutes'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'finish', 'description': 'Report whether you completed the task.',
            'parameters': {
                'type': 'object', 'additionalProperties': False,
                'properties': {'success': {'type': 'boolean'}}, 'required': ['success'],
            },
        },
    },
]


def call_phone(world, token, name, args):
    def read_alarm(alarm_id):
        reply = world.requester._request(
            'phone', 'show_alarm', alarm_id=alarm_id, access_token=token, raise_on_failure=False
        )
        return reply.json().get('snooze_minutes') if reply.status_code == 200 else None

    if name == 'show_alarms' and args == {}:
        response = world.requester._request('phone', 'show_alarms', access_token=token, page_limit=20)
        alarms = [
            {field: alarm[field] for field in ('alarm_id', 'label', 'time', 'repeat_days', 'snooze_minutes')}
            for alarm in response.json()
        ]
        return {'http_status': response.status_code, 'alarms': alarms}, False
    if name == 'update_alarm_snooze' and set(args) == {'alarm_id', 'snooze_minutes'} and all(
        type(value) is int for value in args.values()
    ):
        before = read_alarm(args['alarm_id'])
        response = world.requester._request(
            'phone', 'update_alarm', access_token=token, raise_on_failure=False, **args
        )
        return {
            'http_status': response.status_code, 'response': response.json(),
            'before': before, 'after': read_alarm(args['alarm_id']),
        }, False
    if name == 'finish' and set(args) == {'success'} and type(args['success']) is bool:
        status = 'success' if args['success'] else 'fail'
        response = world.requester._request('supervisor', 'complete_task', status=status)
        return {'http_status': response.status_code, 'response': response.json()}, True
    return {'error': 'Unknown function or invalid arguments.'}, False


def main():
    os.environ['APPWORLD_ROOT'] = str(ROOT / '.appworld')
    from appworld import AppWorld

    row, evaluate_revised = load_alarm_case()
    run_id = f'alarm_smoke_{uuid4().hex[:12]}'
    output = ROOT / 'artifacts' / 'raw' / f'{run_id}.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    messages = [
        {'role': 'system', 'content': 'Use one tool per turn to work in the simulated phone. Call finish when done.'},
        {'role': 'user', 'content': row['modified_spec_b']},
    ]
    result = {'task_id': TASK_ID, 'run_id': run_id, 'kind': 'model_smoke', 'turns': []}
    try:
        with AppWorld(task_id=TASK_ID, experiment_name=run_id) as world:
            token = login_to_simulated_phone(world)
            result['stop_reason'] = 'call_limit'
            for _ in range(6):
                data = complete(messages, tools=TOOLS, purpose=run_id, max_tokens=256)
                message = data['choices'][0]['message']
                calls = message.get('tool_calls') or []
                turn = {'response_id': data['id'], 'usage': data['usage'], 'model_message': message, 'tool_results': []}
                result['turns'].append(turn)
                if not calls:
                    result['stop_reason'] = 'model_stopped_without_finish'
                    break
                messages.append({'role': 'assistant', 'content': message.get('content'), 'tool_calls': calls})
                finished = False
                for call in calls:
                    try:
                        args = json.loads(call['function']['arguments'])
                    except json.JSONDecodeError:
                        args = None
                    if len(calls) != 1 or not isinstance(args, dict):
                        reply = {'error': 'Send one function call with a JSON object per turn.'}
                    else:
                        reply, finished = call_phone(world, token, call['function']['name'], args)
                    turn['tool_results'].append(reply)
                    messages.append({'role': 'tool', 'tool_call_id': call['id'], 'content': json.dumps(reply)})
                if finished:
                    result['stop_reason'] = 'finish'
                    break
            result['score'] = score(world, evaluate_revised, row['evaluation_code'])
    except Exception as error:
        result['infrastructure_error'] = type(error).__name__
        raise
    finally:
        output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'path': str(output), 'stop_reason': result['stop_reason'], 'score': result['score']}))


if __name__ == '__main__':
    main()
