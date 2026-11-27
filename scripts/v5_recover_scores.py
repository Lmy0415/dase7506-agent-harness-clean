"""Restore terminal score-only failures without paying for another rollout."""

import argparse
import ast
import shutil
from pathlib import Path

from scripts.calibrate_alarm import load_case
from scripts.v5_evaluator_audit import score_copy
from src.batch import read
from src.harness_v5 import RAW, RESULTS, ROOT
from src.runner import write_json
from src.v5_sampling import MANIFEST


def relocate(code):
    from appworld.common import utils

    tree = ast.parse(code)
    edits = []
    body = ast.dump(ast.Module(body=[n for n in tree.body if not isinstance(n, (ast.Import, ast.ImportFrom))],
                               type_ignores=[]))
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom) or node.module != 'appworld.common.collections':
            continue
        names = [alias.name for alias in node.names]
        if not set(names) <= {'dict_of', 'flatten', 'lengths_of', 'list_of', 'set_of'}:
            raise ValueError('Unverified collections import.')
        if not all(callable(getattr(utils, name, None)) for name in names):
            raise ImportError('Pinned AppWorld is missing a relocated function.')
        node.module = 'appworld.common.utils'
        edits.extend(names)
    assert body == ast.dump(ast.Module(body=[n for n in tree.body if not isinstance(n, (ast.Import, ast.ImportFrom))],
                                      type_ignores=[]))
    if not edits:
        raise ValueError('No verified relocation was applied.')
    return ast.unparse(tree), edits


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('intervention_id', type=int)
    n = parser.parse_args().intervention_id
    item = next(r for r in read(MANIFEST)['tasks'] if r['intervention_id'] == n)
    row, scorer = load_case(n)
    code, names = relocate(row['evaluation_code'])
    recovered = []
    for arm in (*item['order'], *item['v5_order']):
        folder = RAW / 'v5_new_formal' / f'case_{n}' if arm in item['v5_order'] else ROOT / item['directory']
        path = folder / f'{arm}.json'
        trace = read(path)
        if trace.get('score') is not None:
            continue
        if trace.get('infrastructure_error') != 'ImportError' or not trace.get('stop_reason'):
            raise RuntimeError(f'{arm} did not reach a score-only terminal failure.')
        score, _ = score_copy(n, {**row, 'evaluation_code': code}, scorer, trace)
        if score is None or not score['revised_assertions']:
            raise RuntimeError(f'{arm} cannot be scored from its saved world.')
        archived = path.with_name(f'{arm}.original-score-error.json')
        if archived.exists():
            raise FileExistsError(archived)
        trace['score'] = score
        trace['scoring_recovery'] = {'original_error': trace.pop('infrastructure_error'),
                                     'changed': 'imports only; same saved terminal world and assertion body',
                                     'relocated': names}
        recovered.append((path, archived, trace))
    for path, archived, trace in recovered:
        shutil.copy2(path, archived)
        write_json(path, trace)
        print(n, trace['strategy'], trace['score']['revised_passed'], trace['score']['revised_assertions'])
    write_json(RESULTS / f'new_import_recovery_{n}.json', {
        'intervention_id': n, 'affected_arms': [trace['strategy'] for _, _, trace in recovered],
        'relocated': names, 'assertions_changed': False, 'new_model_calls': 0,
    })


if __name__ == '__main__':
    main()
