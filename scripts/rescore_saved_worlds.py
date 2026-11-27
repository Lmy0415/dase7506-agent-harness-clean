"""Recover scores from terminal simulator databases without invoking the model again."""

import argparse
import json
import shutil
from pathlib import Path

from scripts.calibrate_alarm import load_case
from src.annotations import ANNOTATIONS
from src.model import ROOT
from src.runner import branch_score, world_factory, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('intervention', type=int)
    args = parser.parse_args()
    row, evaluator = load_case(args.intervention)
    _, retained = ANNOTATIONS[args.intervention]
    scored = []
    for arm in 'ABCD':
        path = args.directory / f'{arm}.json'
        trace = json.loads(path.read_text())
        if trace['intervention_id'] != args.intervention or trace.get('infrastructure_error') != 'ModuleNotFoundError':
            raise ValueError('Expected a terminal scoring import failure for the specified case.')
        if trace.get('stop_reason') not in {'simulator_finish', 'model_stopped_without_finish', 'model_call_limit'}:
            raise ValueError('Model execution did not reach a terminal state.')
        state = ROOT / '.appworld' / 'experiments' / 'outputs' / trace['run_id'] / 'tasks' / trace['task_id'] / 'dbs'
        archived = path.with_name(f'{arm}.original-score-error.json')
        if archived.exists():
            raise FileExistsError(archived)
        with world_factory(trace['task_id'], f"{trace['run_id']}_offline_rescore") as world:
            shutil.copytree(state, Path(world.output_checkpoints_directory) / 'terminal')
            world.load_state('terminal')
            world._set_datetime()
            trace['score'] = branch_score(world, row, evaluator, trace, retained)
        trace['scoring_recovery'] = {'original_error': trace.pop('infrastructure_error'),
                                     'source': 'saved terminal AppWorld database',
                                     'change': 'relocated AppWorld evaluator imports'}
        scored.append((path, archived, trace))
    for path, archived, trace in scored:
        shutil.copy2(path, archived)
        write_json(path, trace)
        print(path.stem, trace['score']['revised_passed'], trace['score']['revised_assertions'])


if __name__ == '__main__':
    main()
