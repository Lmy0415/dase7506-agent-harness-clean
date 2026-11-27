"""Score-only sensitivity with verified compatibility corrections, using saved worlds."""

import ast
import json
import os
import shutil
from pathlib import Path

from scripts.calibrate_alarm import load_case
from src import harness_v4
from src.analyze import to_csv
from src.batch import read
from src.harness_v5 import RAW, RESULTS, ROOT
from src.runner import branch_score, world_factory, write_json

AUDIT_CASES = (263, 267, 272, 737, 763)
VERSION = 'compatibility_audit_v1'


def evaluator_for(case, code):
    if case in (267, 272):
        # The upstream wrapper adds Notification to ignore. The explicit include
        # takes precedence in the pinned AppWorld implementation; use both sets.
        target = 'models.changed_model_names(),'
        if code.count(target) != 1:
            raise ValueError('Unexpected notification assertion structure.')
        return code.replace(target, "(models.changed_model_names() | "
                            "models.changed_model_names(include=['venmo.Notification'])),", 1)
    if case == 263:
        old = 'str(getattr(c, "relationship", "")).lower() == "coworker"'
        new = '"coworker" in {str(rel).lower() for rel in getattr(c, "relationships", [])}'
        assert code.count(old) == 1
        code = code.replace(old, new)
        original = 'test.case(cmn - allowed, "==", set())'
        assert code.count(original) == 1
        return code.replace(original, (
            'test.case(cmn - allowed - {"venmo.Transaction"}, "==", set())\n'
            '        adds, edited, removes = models.changed_records("venmo.Transaction")\n'
            '        before = {x.id: x.to_dict() for x in models.changed_records('
            '"venmo.Transaction", updated_state="start")[1]}\n'
            '        after = {x.id: x.to_dict() for x in edited}\n'
            '        unchanged = lambda row: {k: v for k, v in row.items() if k not in ("like_count", "updated_at")}\n'
            '        test.case(not adds and not removes and '
            'all(unchanged(before[k]) == unchanged(after[k]) for k in after), "==", True)'
        ))
    if case == 737:
        class DropReturn(ast.NodeTransformer):
            discarded = 0
            replaced = 0
            cart = 0

            def visit_With(self, node):
                text = ast.unparse(node.items[0].context_expr).lower()
                if 'there is 1 added amazon.productreturn' in text:
                    self.replaced += 1
                    return ast.parse(
                        'with test("Withdrawn return remains unchanged"):\n'
                        '    test.case(sum(len(r) for r in models.changed_records("amazon.ProductReturn")), "==", 0)'
                    ).body[0]
                if 'the product return is for order' in text or 'the product return has data.private.product_id' in text:
                    self.discarded += 1
                    return None
                if 'changed_model_names is a subset' in text:
                    # Apply the evaluator's own earlier cart exclusion consistently.
                    for child in ast.walk(node):
                        if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute) and child.func.attr == 'changed_model_names':
                            child.keywords.append(ast.keyword(arg='ignore', value=ast.List(
                                elts=[ast.Constant('amazon.CartEntry'), ast.Constant('amazon.Address')], ctx=ast.Load())))
                            self.cart += 1
                return node

        rewrite = DropReturn()
        tree = rewrite.visit(ast.parse(code))
        assert (rewrite.discarded, rewrite.replaced, rewrite.cart) == (2, 1, 1)
        return ast.unparse(ast.fix_missing_locations(tree))
    return code


def saved_db(trace):
    return ROOT / '.appworld/experiments/outputs' / trace['run_id'] / 'tasks' / trace['task_id'] / 'dbs'


def score_copy(case, row, scorer, trace):
    from appworld.collections.models import ModelCollectionPair

    base = saved_db(trace)
    if not base.is_dir():
        return None, {}
    # Separate experiment namespace. Never write into archived checkpoints.
    with world_factory(trace['task_id'], f'v5_audit_{case}_{trace["strategy"]}') as world:
        dest = Path(world.output_checkpoints_directory) / 'saved_terminal'
        dest.mkdir(exist_ok=True)
        shutil.copytree(base, dest, dirs_exist_ok=True)
        world.load_state('saved_terminal')
        world._set_datetime()
        details = {}
        if case in (267, 272):
            pair = ModelCollectionPair(start_db_home_path=world.task.model_collection.from_db_home_path,
                                       start_model_collection=world.task.model_collection,
                                       end_db_home_path=world.models.to_db_home_path,
                                       end_model_collection=world.models)
            notification = pair.changed_records('venmo.Notification')
            details['notifications_added'] = len(notification[0])
            details['notification_observed_explicitly'] = 'venmo.Notification' in pair.changed_model_names(
                include=['venmo.Notification'])
        score = branch_score(world, row, scorer, trace, ())
        return score, details


def main():
    os.environ.setdefault('IPYTHONDIR', str(RAW / 'ipython'))
    v4 = {r['intervention_id']: r for r in read(harness_v4.MANIFEST)['tasks']}
    output = []
    for case in AUDIT_CASES:
        item = v4[case]
        source = ROOT / item['directory']
        old = harness_v4.RAW / 'v4_formal' / f'case_{case}'
        new = RAW / 'v5_formal' / f'case_{case}'
        row, scorer = load_case(case)
        score_row = {**row, 'evaluation_code': evaluator_for(case, row['evaluation_code'])}
        traces = [source / f'{arm}.json' for arm in ('A', 'B', 'C', 'D')]
        traces += [old / f'{arm}.json' for arm in ('R', 'C+', 'C++')]
        traces += [new / f'{arm}.json' for arm in ('C5', 'G5') if (new / f'{arm}.json').is_file()]
        for path in traces:
            trace = read(path)
            historical = trace['score']
            revised, details = score_copy(case, score_row, scorer, trace)
            report = {
                'intervention_id': case, 'task_id': item['task_id'], 'strategy': trace['strategy'],
                'version': VERSION, 'rescore': 'done' if revised else 'missing_terminal',
                'original_passed': historical['revised_passed'], 'original_assertions': historical['revised_assertions'],
                'original_final': historical['revised_final_success'], 'original_official': historical['official_pass'],
                'original_strict': historical['strict_success'],
                'audited_passed': (revised or {}).get('revised_passed'), 'audited_assertions': (revised or {}).get('revised_assertions'),
                'audited_final': (revised or {}).get('revised_final_success'), 'audited_official': (revised or {}).get('official_pass'),
                'audited_strict': (revised or {}).get('strict_success'),
                'notifications_added': details.get('notifications_added'),
                'notification_observed_explicitly': details.get('notification_observed_explicitly'),
                'remaining_failed_requirements': ' | '.join(x['requirement'] for x in (revised or {}).get('revised_failures', [])),
                'trace': str(path.relative_to(ROOT)),
            }
            output.append(report)
            print(case, trace['strategy'], report['original_passed'], report['audited_passed'],
                  report['audited_assertions'], details, flush=True)
    to_csv(RESULTS / 'evaluator_audit.csv', output)
    write_json(RESULTS / 'evaluator_audit_version.json', {'version': VERSION,
               'original_scores_unchanged': True, 'audited_interventions': list(AUDIT_CASES),
               'corrected_interventions': [263, 267, 272, 737], 'semantic_ambiguity_unchanged': [763]})


if __name__ == '__main__':
    main()
