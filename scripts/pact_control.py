"""Validate the PACT gates with exact real simulator requests before paid runs."""

import os

from src import checkpoint
from src.batch import read
from src.env_adapter import Simulator
from src.model import ROOT
from src.pact import Controller, boundary_receipt, parse_assessment
from src.pact_cases import LABELS, MANIFEST, RAW, control_notes, monitor_for
from src.pact_score import observe, score
from src.pact_runner import invoke
from src.runner import world_factory, write_json


def main():
    os.environ.setdefault('IPYTHONDIR', str(RAW / 'ipython'))
    pilot = next(i for i in read(MANIFEST)['tasks'] if i['stage'] == 'pilot' and i['slot'] == 'selective')
    results = []
    label = read(LABELS)[str(pilot['intervention_id'])]
    evidence_path = ROOT / pilot['receipt_evidence']
    evidence = read(evidence_path)
    initial = read(evidence_path.with_name('observations.json'))
    for bound in ('PRE', 'POST'):
        with world_factory(pilot['task_id'], f'pact_component_{bound}') as world:
            saved = checkpoint.restore(world, ROOT / pilot['boundary'][bound]['path'])
            sim = Simulator(world, saved['adapter_state'])
            receipt, committed, body = boundary_receipt(saved['history'])
            notes = control_notes()
            cards = {i: {'title': title, 'endpoint': 'simple_note.create_note',
                        'selector': {'title': title, 'content': content},
                        'quote': title, 'deps': deps, 'priority': priority, 'state': 'READY'}
                     for i, ((title, content), deps, priority) in enumerate(
                         zip(notes, [[], [1], [0]], [1, 2, 0]), 1)}
            ctrl = Controller({'old': 'cancel', 'fix': '', 'cards': cards}, receipt, committed, body, sim.catalogue)
            comms = ctrl.messages_to_user()
            start = checkpoint.state_signature(world)
            app, api = receipt['api'].split('.')
            request = {'app': app, 'api': api, 'arguments': receipt['arguments']}
            old = invoke(sim, ctrl, 'call_api', request, pilot['update'], saved['history'])
            assert old['http_status'] == 409 and not old['submitted'] and checkpoint.state_signature(world) == start
            def note(i):
                title, content = notes[i]
                return invoke(sim, ctrl, 'call_api',
                              {'app': 'simple_note', 'api': 'create_note',
                               'arguments': {'title': title, 'content': content}}, pilot['update'], saved['history'])
            early = note(1)
            blocked = note(2)
            assert all(e['http_status'] == 409 and not e['submitted'] for e in (early, blocked))
            assert checkpoint.state_signature(world) == start
            first, second = note(0), note(1)
            assert all(e['http_status'] == 200 and e['submitted'] and e['effect_changed'] for e in (first, second))
            assert checkpoint.state_signature(world) != start and ctrl.selected() is None
            assert [e['tool'] for e in comms] == (['report_conflict', 'request_decision'] if committed else [])
            final = observe(world, pilot, label, evidence)
            transitions = monitor_for(pilot['source'], world).transitions(initial['PRE']['monitor'], final['monitor'])
            def grade(events):
                trace = {'boundary': bound, 'boundary_receipt': receipt['id'], 'automatic_events': comms,
                         'turns': [{'events': events}]}
                return score(pilot, label, trace, initial['PRE'], initial[bound], final, evidence, transitions)
            assert grade([first, second])['arr']
            assert not grade([second, first])['priority']
            assert not grade([])['independent']
            results.append({'boundary': bound, 'receipt_http': 200 if committed else None,
                            'old_request_http': old['http_status'], 'old_request_submitted': old['submitted'],
                            'denied_state_unchanged': True, 'wait_for_approval': committed,
                            'premature_request_denied': True, 'approval_dependency_denied': True,
                            'authorized_note_statuses': [first['http_status'], second['http_status']],
                            'scorer_controls': ['ordered success', 'out-of-order failure', 'global-stop failure']})
    report = {'pilot_intervention_id': pilot['intervention_id'], 'passed': True,
              'checks': results, 'model_calls': 0}
    write_json(RAW / 'component_control.json', report)
    print(report)


if __name__ == '__main__':
    main()
