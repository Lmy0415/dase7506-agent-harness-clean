"""Confirm that a frozen pilot guard leaves a real simulator checkpoint intact."""

from pathlib import Path

from src import checkpoint
from src.batch import read
from src.harness_v4 import GuardedSimulator, RAW, pilot_cases
from src.runner import world_factory, write_json


def main():
    pilot = next(item for item in pilot_cases() if item['intervention_id'] == 750)
    source = Path(pilot['directory'])
    trace = read(RAW / 'v4_confirmation' / 'case_750' / 'C++.json')
    signature = trace['guard_signature']
    prefix = read(source / 'prefix.json')
    with world_factory(pilot['task_id'], 'v4_guard_pilot_control_750') as world:
        restored = checkpoint.restore(world, source / 'checkpoint')
        pending = restored['pending']
        decisions = []
        adapter = GuardedSimulator(world, restored['adapter_state'], signature, decisions)
        before = checkpoint.state_signature(world)
        event = adapter.invoke(pending['name'], pending['arguments'])
        after = checkpoint.state_signature(world)
    probe = prefix['boundary_probe']
    control = {
        'pilot_intervention_id': pilot['intervention_id'], 'api': signature['api'],
        'guard_returned_block': event['response'].get('blocked') is True,
        'guard_http_status': event['http_status'],
        'simulator_submitted': decisions[0]['submitted'], 'unchanged_state': before == after,
        'isolated_probe_http_status': probe['http_status'],
        'isolated_probe_effect': bool(probe['forbidden_transitions']),
        'same_request': pending['arguments'] == probe['request'],
    }
    if not (control['guard_returned_block'] and not control['simulator_submitted'] and control['unchanged_state']
            and control['isolated_probe_effect'] and control['same_request']):
        raise RuntimeError('Guard control did not pass.')
    destination = RAW / 'guard_pilot_control.json'
    write_json(destination, control)
    print(f'Guard control passed: {destination}')


if __name__ == '__main__':
    main()
