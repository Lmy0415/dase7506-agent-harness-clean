"""Render the V4 manuscript's empirical values directly from result tables."""

import csv
import json

from scripts.render_tables import OUTPUT, RESULTS, ratio, table

SOURCE = RESULTS / 'harness_v4'
ARMS = ('A', 'B', 'C', 'R', 'C+', 'C++')


def csv_rows(name):
    with (SOURCE / f'{name}.csv').open(newline='') as handle:
        return list(csv.DictReader(handle))


def usd(nano):
    return int(nano) / 10**9


def rate(row, numerator, denominator='n'):
    return ratio(row[numerator], row[denominator])


def main():
    summary = {(r['cohort'], r['stratum'], r['strategy']): r for r in csv_rows('summary')}
    full = {a: summary['all', 'all', a] for a in (*ARMS, 'D')}
    counts = {arm: rate(row, 'strict_success') for arm, row in full.items() if arm != 'D'}
    pairs = {r['comparison']: r for r in csv_rows('paired') if r['cohort'] == r['stratum'] == 'all'
             and r['outcome'] == 'strict_success' and r['denominator'] == 'all_manifest'}
    budget = json.loads((SOURCE / 'budget.json').read_text())['cumulative']
    if any(r['n'] != r['scored'] for r in full.values()):
        raise ValueError('Complete frozen results or explicitly report missing branches before rendering.')

    main_rows = []
    for arm in ARMS:
        row = full[arm]
        main_rows.append([arm, rate(row, 'scored'), rate(row, 'final_success'), counts[arm],
                          rate(row, 'violation', 'violation_known'), rate(row, 'final_with_violation', 'final_violation_n'),
                          row['supervisor_violation'], row['application_violation'],
                          rate(row, 'retained_pass', 'retained_known')])
    main_table = table('tab:main', 'Frozen, checkpoint-matched continuations. Final is revised goal success. '
                       'Misses are final passes with a monitored violation. Supervisor and application columns count cases.',
                       'lrrrrrrrr',
                       ['Method', 'Scored', 'Final', 'Strict', 'Violation', 'Misses', 'Supervisor',
                        'Application', 'Retention'], main_rows, wide=True)

    strata_rows = [[name.capitalize(), summary[cohort, stratum, 'A']['n'],
                    *[rate(summary[cohort, stratum, a], 'strict_success') for a in ARMS]]
                   for name, cohort, stratum in (('original', 'original', 'all'), ('expansion', 'expansion', 'all'),
                                                ('Swap', 'all', 'Swap'), ('Drop', 'all', 'Drop'))]
    strata_table = table('tab:strata', 'Strict success by batch and by intervention type.', 'lrrrrrrr',
                         ['Group', 'Cases', *ARMS], strata_rows, wide=True)
    pair_rows = [[name, r['first_only'], r['second_only'], r['both_positive'], r['both_negative'],
                  f"{float(r['difference_pp']):+.1f} [{float(r['lower_95_pp']):.1f}, {float(r['upper_95_pp']):.1f}]"]
                 for name, r in pairs.items()]
    paired_table = table('tab:paired', 'Paired strict-success differences in percentage points. Intervals '
                         'use 10,000 task-family bootstrap resamples.', 'lrrrrr',
                         ['Contrast', 'First only', 'Second only', 'Both pass', 'Both fail', r'Difference [95\% CI]'],
                         pair_rows, wide=True)
    cost_rows = []
    for arm in (*ARMS, 'D'):
        r = full[arm]
        n, success = int(r['n']), int(r['success_cost_n'])
        cost_rows.append([arm, f"{int(r['calls']) / n:.1f}", f"{int(r['input_tokens']) / n:,.0f}",
                          f"{int(r['output_tokens']) / n:,.0f}", f"{float(r['wall_seconds']) / n:.1f}",
                          f"{usd(r['peak_nano_usd']) / n:.4f}",
                          f"{usd(r['success_peak_nano_usd']) / success:.4f} ({success})" if success else '--'])
    cost_table = table('tab:cost', 'Means per frozen branch. D includes its initial plan and all execution. '
                       'Success-only cost uses strict success, or final success for D.', 'lrrrrrr',
                       ['Method', 'Calls', 'Input tokens', 'Output tokens', 'Seconds', 'USD', 'USD on success ($n$)'],
                       cost_rows, wide=True)
    d_rows = [[cohort.capitalize(), rate(summary[cohort, 'all', 'D'], 'final_success'),
               rate(summary[cohort, 'all', 'D'], 'official_success')]
              for cohort in ('all', 'original', 'expansion')]
    d_table = table('tab:d', 'Standalone revised task from the initial world.', 'lrr',
                    ['Batch', 'Final', 'Official'], d_rows)
    (OUTPUT / 'tables.tex').write_text('\n\n'.join((main_table, strata_table, paired_table, cost_table, d_table)) + '\n')

    def effect(name):
        return f"{float(pairs[name]['difference_pp']):+.1f}"

    strict_series = ', '.join(f'{arm} {counts[arm]}' for arm in ARMS)
    cplus_ci = pairs['C+ vs C']
    guard = full['C++']
    guard_total = sum(int(guard[key]) for key in ('allow', 'unknown', 'block'))
    budget_upper = usd(budget['total_peak_nano_usd']) + usd(budget['outstanding_reservations_nano_usd'])
    app_cases = sum(int(full[arm]['application_violation']) for arm in ARMS)

    (OUTPUT / 'abstract.tex').write_text(
        'When a user revises a goal after tool execution has begun, an agent must identify what still applies '
        'and reuse effects already committed. We compare instruction consolidation, plan editing with explicit intent '
        'and execution receipts, and a narrowly scoped execution check against three continuation baselines. '
        f'The methods share a pre-write AppWorld checkpoint on {full["A"]["n"]} InterventionBench task families. '
        f'Strict success counts were {strict_series}. The difference for intent-aware editing versus local editing '
        f'was {effect("C+ vs C")} percentage points (95\\% paired bootstrap interval '
        f'[{float(cplus_ci["lower_95_pp"]):.1f}, {float(cplus_ci["upper_95_pp"]):.1f}]). '
        f'The check blocked {guard["block"]} of {guard_total} evaluated requests. '
        'These exploratory comparisons characterize the representation of intent and receipts '
        'under a fixed executor and model, with state changes evaluated independently of the agent.\n'
    )
    currency = r'\$'
    (OUTPUT / 'results.tex').write_text(r'''\section{Results}
\input{generated/tables.tex}
\subsection{Strict success and paired effects}
''' + f'''All {sum(int(r['scored']) for r in full.values())} expected branches were scored, including the standalone comparison.
Table~\\ref{{tab:main}} gives the fixed-denominator comparison. The intent-aware editor changed strict success by {effect('C+ vs C')} points versus C and {effect('C+ vs R')} points versus R.
R changed strict success by {effect('R vs A')} points versus native continuation.
Guarded editing changed strict success by {effect('C++ vs C+')} points versus unguarded intent-aware editing.
Table~\\ref{{tab:paired}} shows discordant and concordant pairs and their uncertainty. Table~\\ref{{tab:strata}} separates the two batches and intervention types.

\\subsection{{Violations, coverage, and cost}}
Table~\\ref{{tab:main}} shows final passes with a committed withdrawn effect.
The supervisor column covers stale answers or completion-related operations. Application violations alter simulator application state.
The formal continuations recorded {app_cases} branches with a monitored application violation.
Case-specific predicates bound the scope of both counts. Retention has no separately labeled assertion in the formal cohorts.

C+ fell back to native continuation in {full['C+']['fallback']}/{full['C+']['n']} branches, and C++ fell back in {guard['fallback']}/{guard['n']}.
C+ flagged {full['C+']['evidence_validation_errors']} evidence-related validation errors across all structured attempts.
C++ inferred a signature in {guard['guard_signature']}/{guard['n']} branches.
Of {guard_total} evaluated requests it allowed {guard['allow']}, left {guard['unknown']} uncertain, and blocked {guard['block']}.
The independent audit confirmed {guard['confirmed_conflict']} conflicts and {guard['confirmed_nonconflict']} nonconflicts. It left {guard['unknown_block']} blocked requests unclassified.
The audit uses the isolated probe for a blocked request only if it exactly matches the pending request and no intervening simulator call may have altered the state.
When no requests can be independently adjudicated, a false-block rate is undefined.

Table~\\ref{{tab:cost}} reports cost on all branches and on successful branches. Early stopping can reduce the cost of a failed run.
Including setup, pilots, screening, and all formal branches, the ledger contains {budget['settled_model_calls']:,} returned requests.
Their peak-price upper bound was {currency}{usd(budget['total_peak_nano_usd']):.4f}.
Unresolved reservations added {currency}{usd(budget['outstanding_reservations_nano_usd']):.4f}, for {currency}{budget_upper:.4f} against the {currency}10 limit.
Table~\\ref{{tab:d}} reports D as a separate difficulty reference.
''' + ('\nThe guard did not intervene in the formal trajectories, so the observed difference from C+ '
        'cannot be attributed to blocking an operation.\n' if int(guard['block']) == 0 else '')
        + '\n\\IfFileExists{generated/case_analysis.tex}{\\input{generated/case_analysis.tex}}{}\n')
    (OUTPUT / 'conclusion.tex').write_text(
        '\\section{Conclusion}\n'
        f'On {full["A"]["n"]} matched families, intent-aware editing recorded {counts["C+"]} strict successes, '
        f'compared with {counts["C"]} for local editing and {counts["R"]} for instruction consolidation. '
        f'The guarded variant recorded {counts["C++"]}. The differences reflect the combined effects of '
        'state presentation and plan editing, along with the behavior of the shared model. '
        'The checkpoint design reveals withdrawn effects that revised final-state scoring can miss. '
        'The comparison applies to these recoverable interruptions and the specific predicates and model.\n'
    )
    (OUTPUT / 'numbers.tex').write_text(f'\\newcommand{{\\StudyCases}}{{{full["A"]["n"]}}}\n')


if __name__ == '__main__':
    main()
