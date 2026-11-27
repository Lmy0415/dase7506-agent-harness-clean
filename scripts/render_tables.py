"""Render LaTeX result tables from formal CSVs without copying raw trace content."""

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / 'results'
OUTPUT = ROOT / 'paper' / 'generated'
NAMES = {'A': 'A: Native continuation', 'B': 'B: Full replanning', 'C': 'C: Local revision', 'D': 'D: Standalone revised goal'}


def read_table(name):
    with (RESULTS / f'{name}.csv').open(newline='') as handle:
        return list(csv.DictReader(handle))


def ratio(num, den):
    num = int(num or 0)
    den = int(den or 0)
    return f'{num}/{den}' if den else '--'


def tex_row(values):
    return ' & '.join(map(str, values)) + r' \\'


def table(label, caption, columns, heading, rows, wide=False):
    environment = 'table*' if wide else 'table'
    return '\n'.join([
        rf'\begin{{{environment}}}[t]', r'\centering', rf'\caption{{{caption}}}', rf'\label{{{label}}}',
        r'\small', rf'\begin{{tabular}}{{{columns}}}', r'\toprule', tex_row(heading), r'\midrule',
        *(tex_row(row) for row in rows), r'\bottomrule', r'\end{tabular}', rf'\end{{{environment}}}',
    ])


def numbers(stats, paired_stats):
    full = {r['strategy']: r for r in stats if r['stratum'] == 'All' and r['cohort'] == 'Full'}
    d = next(r for r in stats if r['strategy'] == 'D' and r['stratum'] == 'All' and r['cohort'] == 'D-matched')
    budget = json.loads((RESULTS / 'budget.json').read_text())
    costs = {r['stage']: int(r['peak_nano_usd']) / 1e9 for r in read_table('cost_breakdown')}
    metrics = read_table('branch_metrics')
    by_family = {}
    for row in metrics:
        by_family.setdefault(row['family_id'], {})[row['strategy']] = row
    values = {'StudyCases': full['A']['n'], 'StandaloneCases': d['n'], 'StandaloneSuccess': d['final_success'],
              'ScoredBranches': sum(row['status'] == 'scored' for row in metrics),
              'DOnly': sum(arms.get('D', {}).get('revised_final_success') == '1'
                           and all(arms[arm]['strict_success'] == '0' for arm in 'ABC') for arms in by_family.values()),
              'MatchedOnly': sum(arms.get('D', {}).get('revised_final_success') == '0'
                                 and any(arms[arm]['strict_success'] == '1' for arm in 'ABC') for arms in by_family.values()),
              'TotalReceipts': budget['settled_model_calls'],
              'PeakCost': f"{budget['total_peak_nano_usd'] / 1e9:.4f}",
              'ScheduledCost': f"{budget['scheduled_charge_estimate_nano_usd'] / 1e9:.4f}",
              'UnresolvedCost': f"{budget['outstanding_reservations_nano_usd'] / 1e9:.4f}",
              'PrefixCost': f"{costs['formal_prefix_admitted'] + costs['formal_prefix_not_admitted']:.4f}",
              'SharedPrefixCost': f"{costs['formal_prefix_admitted']:.4f}",
              'RejectedPrefixCost': f"{costs['formal_prefix_not_admitted']:.4f}",
              'StandaloneCost': f"{costs['formal_D']:.4f}"}
    for arm, row in full.items():
        for name, field in [('Strict', 'strict_success'), ('Final', 'final_success'),
                            ('Violation', 'violations'), ('Miss', 'misses'), ('MissDen', 'miss_n')]:
            values[f'{name}{arm}'] = row[field]
    for row in paired_stats:
        if row['stratum'] == 'All' and row['denominator'] == 'all_manifest':
            label = row['comparison'].replace('-', '')
            values[f'Delta{label}'] = f"{float(row['difference_pp']):+.2f}"
            values[f'LBound{label}'] = f"{float(row['lower_95_pp']):.2f}"
            values[f'UBound{label}'] = f"{float(row['upper_95_pp']):.2f}"
            values[f'Gains{label}'], values[f'Losses{label}'] = row['improved'], row['regressed']
    return '\n'.join(rf'\newcommand{{\{name}}}{{{value}}}' for name, value in sorted(values.items())) + '\n'


def main():
    stats = read_table('summary')
    effects = read_table('paired')
    reports = []
    full_rows = []
    for r in stats:
        if r['cohort'] != 'Full' or r['stratum'] != 'All':
            continue
        n = r['n']
        mean_cost = int(r['peak_nano_usd']) / 1e9 / int(n)
        full_rows.append([NAMES[r['strategy']], r['scored'], ratio(r['final_success'], n),
                          ratio(r['official_pass'], n), ratio(r['violations'], r['violation_n']),
                          ratio(r['retained_pass'], r['retained_required']), ratio(r['strict_success'], n),
                          ratio(r['misses'], r['miss_n']), f'{mean_cost:.4f}'])
    reports.append(table(
        'tab:main', 'Formal comparison. Fractions report counts over the applicable denominators. An em dash denotes an empty denominator. Cost is the peak-price upper bound per frozen branch in USD.',
        'lrrrrrrrr', ['Method', 'Scored', 'Revised', 'Official', 'Violations', 'Retained', 'Strict', 'Misses', 'Cost'],
        full_rows, wide=True,
    ))
    group_rows = {(r['stratum'], r['strategy']): r for r in stats if r['cohort'] == 'Full'}
    strata = []
    for kind in ('Swap', 'Drop'):
        for arm in 'ABC':
            if (kind, arm) in group_rows:
                r = group_rows[kind, arm]
                strata.append([kind, arm, ratio(r['final_success'], r['n']), ratio(r['strict_success'], r['n']),
                               ratio(r['violations'], r['violation_n'])])
    reports.append(table('tab:strata', 'Formal results by intervention type.', 'llrrr',
                         ['Type', 'Method', 'Revised', 'Strict', 'Violations'], strata))
    pair_rows = []
    for r in effects:
        if r['stratum'] == 'All' and r['denominator'] == 'all_manifest':
            estimate = float(r['difference_pp'])
            low, high = float(r['lower_95_pp']), float(r['upper_95_pp'])
            pair_rows.append([r['comparison'], r['improved'], r['regressed'], f'{estimate:+.2f} [{low:.2f}, {high:.2f}]'])
    reports.append(table(
        'tab:paired', 'Paired strict-success differences in percentage points. Each interval comes from 10,000 family-level bootstrap resamples.',
        'lrrr', ['Contrast', 'Gains', 'Losses', 'Difference [95\\% CI]'], pair_rows,
    ))
    d_rows = []
    for r in stats:
        if r['cohort'] == 'D-matched' and r['stratum'] == 'All':
            d_rows.append([NAMES[r['strategy']], r['n'], ratio(r['final_success'], r['n']), ratio(r['official_pass'], r['n'])])
    reports.append(table(
        'tab:standalone', 'Difficulty comparison on the frozen D subset. A, B, and C use their shared prefix. D starts from the initial world.',
        'lrrr', ['Method', 'Cases', 'Revised', 'Official'], d_rows,
    ))
    OUTPUT.mkdir(exist_ok=True)
    (OUTPUT / 'tables.tex').write_text('\n\n'.join(reports) + '\n')
    (OUTPUT / 'numbers.tex').write_text(numbers(stats, effects))


if __name__ == '__main__':
    main()
