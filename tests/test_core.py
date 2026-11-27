"""Guards for the state and reporting invariants used by the formal evaluation."""

import unittest
from unittest.mock import patch

from src.analyze import paired, summaries
from src.monitor import Monitor
from src.strategies import initial_plan, local_revision


class StudyInvariants(unittest.TestCase):
    def test_local_patch_retains_untouched_order(self):
        original = initial_plan('{"steps":["reuse draft","send to A","send to B"]}')
        result = local_revision(original, '{"edits":[{"id":2,"op":"delete"},'
                                         '{"id":3,"op":"replace","steps":["check address","send to C"]}]}')
        self.assertEqual(result, ['reuse draft', 'check address', 'send to C'])
        self.assertEqual(local_revision(original, '{"edits":[]}'),
                         ['reuse draft', 'send to A', 'send to B'])
        with self.assertRaises(ValueError):
            local_revision(original, '{"edits":[{"id":2,"op":"delete"},{"id":2,"op":"keep"}]}')

    def test_forbidden_transition_counts_effect_and_survives_undo(self):
        monitor = Monitor([{'model': 'phone.Alarm', 'effect': 'set',
                            'where': {'label': 'weekday'}, 'new_values': {'snooze_minutes': 5}}])
        original = [{'1': {'label': 'weekday', 'snooze_minutes': 10},
                     '2': {'label': 'weekend', 'snooze_minutes': 10}}]
        changed = [{'1': {'label': 'weekday', 'snooze_minutes': 5},
                    '2': {'label': 'weekend', 'snooze_minutes': 10}}]
        commit = {'before': original, 'after': changed, 'http_status': 200}
        no_effect = {'before': original, 'after': original, 'http_status': 409}
        undo = {'before': changed, 'after': original, 'http_status': 200}
        for event in (commit, no_effect, undo):
            monitor.summarize(event)
        self.assertEqual(commit['forbidden_transitions'], [{'rule': 0, 'record_id': '1', 'effect': 'set'}])
        self.assertEqual(no_effect['forbidden_transitions'], [])
        self.assertEqual(undo['forbidden_transitions'], [])
        self.assertTrue(any(event['forbidden_transitions'] for event in (commit, undo)))

    @staticmethod
    def row(family, arm, strict, observed=True, violation=0):
        return {
            'family_id': family, 'stratum': 'Swap', 'd_subset': 1, 'strategy': arm,
            'strict_success': strict, 'status': 'scored' if observed else 'missing',
            'violation': violation if observed and arm != 'D' else None,
            'official_pass': strict, 'revised_final_success': strict,
            'retained_pass': 0, 'retained_required': 0, 'retained_unknown': 0,
            'input_tokens': 0, 'output_tokens': 0, 'peak_nano_usd': 0,
        }

    def test_missing_branch_remains_in_paired_primary_denominator(self):
        rows = [
            self.row('f1', 'A', 1), self.row('f1', 'B', 1), self.row('f1', 'C', 1),
            self.row('f2', 'A', 0), self.row('f2', 'B', 0, observed=False), self.row('f2', 'C', 1),
        ]
        with patch('src.analyze.RESAMPLES', 20):
            observed = {(r['denominator'], r['comparison']): r for r in paired(rows) if r['stratum'] == 'All'}
        primary = observed['all_manifest', 'C-B']
        sensitivity = observed['both_scored', 'C-B']
        self.assertEqual((primary['n'], primary['improved'], primary['difference_pp']), (2, 1, 50))
        self.assertEqual((sensitivity['n'], sensitivity['improved']), (1, 0))

    def test_violation_and_final_miss_denominators(self):
        rows = [self.row('f1', 'A', 1, violation=1), self.row('f2', 'A', 0, observed=False)]
        metric = next(r for r in summaries(rows) if r['cohort'] == 'Full' and r['stratum'] == 'All')
        self.assertEqual((metric['n'], metric['violation_n'], metric['violation_unknown']), (2, 1, 1))
        self.assertEqual((metric['misses'], metric['miss_n']), (1, 1))


if __name__ == '__main__':
    unittest.main()
