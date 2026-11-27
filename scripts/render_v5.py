"""Render the final paper from the archived V5 result CSVs."""

import csv
import json

from scripts.render_tables import OUTPUT, RESULTS, ratio, table

SOURCE = RESULTS / 'harness_v5'
HIST = 'historical_40'
NEW = 'new_families'
ARMS = ('A', 'B', 'C', 'R', 'C+', 'C++', 'C5', 'G5', 'D')


def rows(name):
    with (SOURCE / f'{name}.csv').open() as handle:
        return list(csv.DictReader(handle))


def item(row, statistic, denominator='n'):
    return ratio(row[statistic], row[denominator])


def usd(value):
    return int(value) / 10**9


def main():
    summary = {(r['cohort'], r['stratum'], r['arm']): r for r in rows('summary')}
    historical = {arm: summary[HIST, 'all', arm] for arm in ARMS if (HIST, 'all', arm) in summary}
    fresh = {arm: summary[NEW, 'all', arm] for arm in ARMS if (NEW, 'all', arm) in summary}
    assert all(row['scored'] == row['n'] for row in (*historical.values(), *fresh.values()))
    pairs = [r for r in rows('paired') if r['stratum'] == 'all']
    audit = rows('sensitivity')
    offline = {(r['dataset'], r['scope'], r['policy']): r for r in rows('guard_offline_metrics')}
    diag = json.loads((SOURCE / 'diagnosis.json').read_text())
    budget = json.loads((SOURCE / 'budget.json').read_text())
    total = budget['actual_cumulative']
    screening = rows('new_screening') if (SOURCE / 'new_screening.csv').is_file() else []
    screened = sum(bool(r['prefix_calls']) for r in screening)

    def arm_table(label, title, group):
        stats = [
            [arm, item(row, 'final'), item(row, 'official'),
             item(row, 'strict') if arm != 'D' else '--',
             item(row, 'supervisor_violation', 'known_violation_n'),
             item(row, 'application_violation', 'known_violation_n'),
             item(row, 'missed_violation', 'miss_n'),
             f"{usd(row['logical_peak_nano_usd']) / int(row['n']):.4f}",
             f"{usd(row['success_logical_peak_nano_usd']) / int(row['successful_n']):.4f}"
             if int(row['successful_n']) else '--']
            for arm, row in group.items()
        ]
        return table(label, title, 'lrrrrrrrr', ['Arm', 'Final', 'Official', 'Strict', 'Supervisor', 'Application',
                                               'Misses', 'USD', 'USD if success'], stats, wide=True)

    tables = [arm_table('tab:history', 'Historical cohort, frozen primary scores. Costs are logical mean USD '
                        'per branch and conditional on strict or standalone success.', historical)]
    if fresh:
        tables.append(arm_table('tab:confirm', 'Unused-family confirmation. The columns match Table~\\ref{tab:history}.',
                                fresh))
    groups = [('Historical swap', HIST, 'Swap'), ('Historical drop', HIST, 'Drop'),
              ('New swap', NEW, 'Swap'), ('New drop', NEW, 'Drop')]
    methods = ('A', 'C', 'C+', 'C5', 'G5')
    strata_rows = [
        [label, summary[cohort, stratum, 'A']['n'], *[
            item(summary[cohort, stratum, arm], 'strict') if (cohort, stratum, arm) in summary else '--'
            for arm in methods]]
        for label, cohort, stratum in groups if (cohort, stratum, 'A') in summary
    ]
    tables.append(table('tab:strata', 'Strict success by cohort and intervention type.', 'lrrrrrr',
                        ['Group', 'Cases', *methods], strata_rows, wide=True))
    effects = [
        ['Hist.' if r['cohort'] == HIST else 'New', f"{r['first']} vs {r['second']}", r['n'],
         r['first_only'], r['second_only'], r['both'], r['neither'],
         f"{float(r['delta_pp']):+.1f} [{float(r['low_95']):.1f}, {float(r['high_95']):.1f}]"]
        for r in pairs
    ]
    tables.append(table('tab:paired', 'Strict-success switches and family-bootstrap intervals in percentage points.',
                        'llrrrrrr', ['Cohort', 'Contrast', 'Cases', 'First only', 'Second only',
                                     'Both', 'Neither', r'Difference [95\% CI]'], effects, wide=True))
    tables.append(table('tab:audit', 'Independent sensitivity scores for the historical cohort. D uses revised '
                        'final success. Other methods use strict success.', 'lrrrr',
                        ['Arm', 'Cases', 'Frozen', 'Audited', 'Gain'],
                        [[r['arm'], r['n'], r['original'], r['revised'], r['gains']] for r in audit]))
    (OUTPUT / 'tables.tex').write_text('\n\n'.join(tables) + '\n')

    baseline = historical['C+']
    c5, g5 = historical['C5'], historical.get('G5')
    probe = offline['boundary_probe', 'application', 'v5']
    natural = offline['natural_2xx', 'all', 'v5']
    control = offline['pilot_control', 'all', 'v5']
    diff = next(r for r in pairs if (r['cohort'], r['first'], r['second']) == (HIST, 'C5', 'C+'))
    interval = f"[{float(diff['low_95']):.1f}, {float(diff['high_95']):.1f}]"
    hist_guard = (f"The guarded method blocked {g5['guard_block']} of {g5['guard_checked']} checked historical "
                  f"requests and had {item(g5, 'strict')} strict successes. ") if g5 else ''
    (OUTPUT / 'abstract.tex').write_text(
        'Agents that receive revised goals during tool use must distinguish revoked actions, retained work, and '
        'completed effects. We evaluate matched AppWorld continuations before a verified withdrawn write. '
        f"Across {c5['n']} historical families, tolerant local validation reduced full fallback from "
        f"{item(baseline, 'fallback')} to {item(c5, 'fallback')}, while strict success was "
        f"{item(c5, 'strict')} for both intent-aware revisions "
        f"(paired difference {float(diff['delta_pp']):+.1f} points, 95\\% bootstrap interval {interval}). "
        + hist_guard
        + (f"A separate confirmation cohort included {fresh['C5']['n']} unused families. " if fresh else '')
        + 'An independent scoring audit identified compatibility and instruction conflicts. '
        'The study separates structural reliability from task completion, and guard detection from the '
        'opportunity to enforce it.\n'
    )
    dollar = r'\$'
    explanation = r'''\section{Results}
\input{generated/tables.tex}
\subsection{Offline structure and guard tests}
''' + (
        f"Among the {diag['cases']} saved C+ responses and any repairs, the original parser admitted full state "
        f"for {diag['legacy_full']} families. Representation normalization alone reached {diag['normalized_full']}. "
        f"After checking evidence and preserving independent modules, C5 retained {diag['c5_full']} full and "
        f"{diag['c5_partial']} partial states. These replay counts measure representation and evidence quality.\n\n"
        f"The guard replay used {natural['n']} natural successful requests. Of these, "
        f"{natural['unknown_label']} had unknown labels. The {natural['fn']} confirmed natural positives were "
        'supervisor answer submissions. Both policies missed them. No application-side violation was '
        'observed in these historical natural trajectories, so application recall cannot be estimated there. '
        f"G5 caught {probe['tp']}/{probe['n']} isolated application-positive boundary probes. The real pilot "
        f"control yielded {control['tp']} correct block and {control['tn']} correct allow. The positive probes "
        'were selected by construction and contain no negative examples.\n\n'
        '\\subsection{Checkpoint-matched execution}\n'
        'Tables~\\ref{tab:history} and \\ref{tab:paired} report frozen primary outcomes. '
        f"On the historical families, C5 yielded {c5['full']} full, {c5['partial']} partial, and "
        f"{c5['fallback']} fallback states. It downgraded evidence for {c5['evidence_downgraded_steps']} steps. "
        f"The historical C5 versus C+ contrast has {diff['first_only']} gain and {diff['second_only']} loss. "
        'Tables separate swaps and partial drops. Retention has no independent formal denominator.\n\n'
    )
    if g5:
        explanation += (
            f"G5 derived rules on {item(g5, 'guard_rules')} historical families and evaluated "
            f"{g5['guard_checked']} tool requests. It blocked {g5['guard_block']} and marked "
            f"{g5['guard_unknown']} unknown. The audit could independently verify "
            f"{g5['guard_confirmed_conflict']} true conflicts and {g5['guard_confirmed_nonconflict']} false blocks. "
            'Case-level differences can arise from the later model generations.\n\n'
        )
    if fresh:
        explanation += (
            f"The prespecified unused-family queue yielded {fresh['C5']['n']} qualified families from "
            f"{screened} prefix attempts. C5 achieved {item(fresh['C5'], 'strict')}, compared with "
            f"{item(fresh['C'], 'strict')} for C and {item(fresh['A'], 'strict')} for A "
            '(Table~\\ref{tab:confirm}). The new sample is reported separately because admission is conditional '
            'and its small number of families limits precision. A zero-width interval records a sample '
            'with no discordant pairs.\n\n'
        )
    total_use = usd(total['total_peak_nano_usd']) + usd(total['outstanding_reservations_nano_usd'])
    charged = sum(int(v.get('peak_nano_usd', 0)) for phase in budget['v5_true_use_by_phase'].values() for v in phase.values())
    requests = sum(int(v.get('calls', 0)) for phase in budget['v5_true_use_by_phase'].values() for v in phase.values())
    explanation += (
        '\\subsection{Cost and evaluator sensitivity}\n'
        f"V5 returned {requests:,} token receipts, with a peak-price estimate of {dollar}{usd(charged):.4f}. "
        f"The cumulative project occupation including unresolved reservations was {dollar}{total_use:.4f} "
        f"of {dollar}10. The logical cost columns charge each arm for shared planning, while the cash ledger "
        'counts each shared revision once. Short failed runs can lower average cost.\n\n'
        'Table~\\ref{tab:audit} applies compatibility corrections uniformly to the audited families using saved '
        'terminal states. The original evaluator is the primary measure. Correcting a model-diff inconsistency '
        'or a withdrawn return assertion is a change in measurement. It does not alter the agents or their traces.\n\n'
        '\\input{generated/case_analysis.tex}\n'
    )
    (OUTPUT / 'results.tex').write_text(explanation)
    (OUTPUT / 'conclusion.tex').write_text(
        '\\section{Conclusion}\n'
        'Local compatibility checks retained usable state much more often. '
        f"On {c5['n']} historical families C5 had {item(c5, 'strict')} strict successes, versus "
        f"{item(baseline, 'strict')} for C+ and {item(historical['C'], 'strict')} for ordinary local editing. "
        'The guard recognized some isolated withdrawals. Its natural opportunities and argument coverage were limited. '
        'Reporting the guard, task outcome, and evaluator audit separately exposed failures that a single success rate obscures.\n'
    )
    (OUTPUT / 'numbers.tex').write_text(f"\\newcommand{{\\StudyCases}}{{{c5['n']}}}\n")


if __name__ == '__main__':
    main()
