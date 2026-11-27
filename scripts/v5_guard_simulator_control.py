"""Exercise the V5 guard on an isolated, real pilot checkpoint without an API call."""

from src import checkpoint, harness_v4
from src.batch import read
from src.guard_v5 import guard_rule
from src.harness_v5 import GuardedSimulator, RESULTS
from src.intent_revision import visible_receipts
from src.runner import world_factory, write_json
from scripts.calibrate_alarm import load_case


def main():
    item = next(i for i in harness_v4.pilot_cases() if i['intervention_id'] == 750)
    row, _ = load_case(item['intervention_id'])
    trace = read(harness_v4.RAW / 'v4_confirmation/case_750/C++.json')
    with world_factory(item['task_id'], 'v5_pilot_guard_control') as world:
        restored = checkpoint.restore(world, harness_v4.ROOT / item['directory'] / 'checkpoint')
        intent = trace['state_at_revision']['intent']
        rule, reason = guard_rule(intent, visible_receipts(restored['history']), row['intervention_text'])
        assert rule is not None, reason
        checks = []
        simulator = GuardedSimulator(world, restored['adapter_state'], rule, checks)
        before = checkpoint.state_signature(world)
        pending = restored['pending']
        blocked = simulator.invoke(pending['name'], pending['arguments'])
        after = checkpoint.state_signature(world)
        pos = checks[0]
        assert pending['arguments']['api'] == 'send_email_from_draft'
        # Continue through the same executor interface with a retained read.
        draft = pending['arguments']['arguments']['draft_id']
        continued = simulator.invoke('call_api', {'app': 'gmail', 'api': 'show_draft',
                                                   'arguments': {'draft_id': draft}})
        control = {'pilot_intervention_id': item['intervention_id'], 'api': rule['api'],
                   'blocked': blocked['http_status'] == 409 and not pos['submitted'],
                   'unchanged': before == after,
                   'continued': continued['http_status'] == 200 and checks[1]['decision'] == 'allow'}
    write_json(RESULTS / 'guard_simulator_control.json', control)
    assert all(control[key] for key in ('blocked', 'unchanged', 'continued'))
    print(control)


if __name__ == '__main__':
    main()
