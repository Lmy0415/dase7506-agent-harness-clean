"""Verify independent AppWorld recovery after a retained write has committed."""

import json
import os
from uuid import uuid4

from scripts.calibrate_alarm import ROOT, login_to_simulated_phone
from src import checkpoint

TASK = '771d8fc_1'
INTERVENTION = 266


def main():
    os.environ['APPWORLD_ROOT'] = str(ROOT / '.appworld')
    from appworld import AppWorld

    run_id = f'drop_check_{uuid4().hex[:10]}'
    destination = ROOT / 'artifacts' / 'checkpoints' / run_id
    result_path = ROOT / 'artifacts' / 'raw' / f'{run_id}.json'
    result_path.parent.mkdir(parents=True, exist_ok=True)

    with AppWorld(task_id=TASK, experiment_name=f'{run_id}_prefix', random_seed=7506) as world:
        token = login_to_simulated_phone(world)
        phone_number = '3654328626'  # The number appears in the official visible task instruction.
        texts = world.apis.phone.search_text_messages(phone_number=phone_number, access_token=token, page_limit=20)
        voices = world.apis.phone.search_voice_messages(phone_number=phone_number, access_token=token, page_limit=20)
        text_id = next(m['text_message_id'] for m in texts if m['sender']['phone_number'] == phone_number)
        voice_id = next(m['voice_message_id'] for m in voices if m['sender']['phone_number'] == phone_number)

        write = world.requester._request('phone', 'delete_text_message', text_message_id=text_id, access_token=token)
        old_plan = [
            {'id': 1, 'text': 'Find incoming messages from the specified phone number.'},
            {'id': 2, 'text': 'Delete its text messages.'},
            {'id': 3, 'text': 'Delete its voice messages.'},
        ]
        pending = {'tool': 'phone.delete_voice_message', 'arguments': {'voice_message_id': voice_id}, 'committed': False}
        history = [
            {'role': 'user', 'content': world.task.instruction},
            {'role': 'assistant', 'content': json.dumps(old_plan)},
            {'role': 'tool', 'content': write.text},
        ]
        manifest = checkpoint.save(
            world, destination, history=history, old_plan=old_plan, pending=pending,
            tool_log=[{'tool': 'phone.delete_text_message', 'status': write.status_code}],
        )

    observations = {}
    for branch in ('probe', 'clean'):
        with AppWorld(task_id=TASK, experiment_name=f'{run_id}_{branch}', random_seed=7506) as world:
            restored = checkpoint.restore(world, destination)

            def read_status(tool, **kwargs):
                return world.requester._request(
                    'phone', tool, access_token=token, raise_on_failure=False, track=False, **kwargs
                ).status_code

            voice_before = read_status('show_voice_message', voice_message_id=voice_id)
            text_before = read_status('show_text_message', text_message_id=text_id)
            branch_record = {
                'state': restored['state'], 'context_sha256': restored['context_sha256'],
                'text_before_http': text_before, 'voice_before_http': voice_before,
            }
            if branch == 'probe':
                branch_record['probe_http'] = world.requester._request(
                    'phone', 'delete_voice_message', voice_message_id=voice_id, access_token=token
                ).status_code
            branch_record['voice_after_http'] = read_status('show_voice_message', voice_message_id=voice_id)
            observations[branch] = branch_record

    result = {'run_id': run_id, 'task_id': TASK, 'intervention_id': INTERVENTION,
              'state': manifest['state'], 'observations': observations}
    result_path.write_text(json.dumps(result, indent=2) + '\n')
    probe, clean = observations['probe'], observations['clean']
    if not (probe['text_before_http'] == clean['text_before_http'] != 200
            and probe['voice_before_http'] == clean['voice_before_http'] == clean['voice_after_http'] == 200
            and probe['probe_http'] == 200 and probe['voice_after_http'] != 200):
        raise RuntimeError(f'Checkpoint recovery failed. See {result_path}.')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
