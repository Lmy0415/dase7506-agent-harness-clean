"""Render the IEEE single-column ARR figure from the frozen PACT summary."""

import csv
from fractions import Fraction
from pathlib import Path

import matplotlib

matplotlib.use('Agg')
from matplotlib import pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'results/pact/summary.csv'
OUTPUT = ROOT / 'paper/figures/commitment_arr'
BOUNDARIES = ('PRE', 'POST')
EXPECTED = {'A': ((11, 12), (2, 12)), 'P': ((10, 12), (2, 12)), 'PACT': ((10, 12), (7, 12))}


def load_rates():
    counts = {}
    with SOURCE.open(newline='', encoding='utf-8') as handle:
        for row in csv.DictReader(handle):
            if row['stage'] != 'formal' or row['stratum'] != 'all':
                continue
            key = (row['method'], row['boundary'])
            if key in counts:
                raise ValueError(f'Duplicate summary row for {key}.')
            counts[key] = (int(row['arr']), int(row['arr_n']))
    expected = {(method, boundary): pair for method, pairs in EXPECTED.items()
                for boundary, pair in zip(BOUNDARIES, pairs, strict=True)}
    if counts != expected:
        raise ValueError(f'Unexpected formal ARR counts in {SOURCE}: {counts}')
    return {method: [100 * Fraction(*counts[method, boundary]) for boundary in BOUNDARIES]
            for method in EXPECTED}


def main():
    rates = load_rates()
    gray, orange, teal = '#646464', '#AF591F', '#00575B'
    styles = {
        'A': dict(label='Native (A)', color=gray, linestyle='-', linewidth=1.15,
                  marker='s', markersize=4.4),
        'P': dict(label='Procedure Prompt (P)', color=orange, linestyle=(0, (4, 2.5)),
                  linewidth=1.25, marker='D', markersize=7.1, markerfacecolor='none'),
        'PACT': dict(label='PACT (Ours)', color=teal, linestyle='-', linewidth=2.2,
                     marker='o', markersize=4.5),
    }
    with plt.rc_context({'font.family': 'DejaVu Sans', 'font.size': 8, 'pdf.fonttype': 42}):
        fig, ax = plt.subplots(figsize=(3.45, 2.65))
        fig.subplots_adjust(left=.175, right=.974, bottom=.235, top=.79)
        for method in EXPECTED:
            ax.plot((0, 1), rates[method], **styles[method])
        ax.set(xlim=(-.2, 1.91), ylim=(0, 100),
               ylabel='Appropriate Resolution Rate (%)',
               xticks=(0, 1), xticklabels=('PRE (Before Commit)', 'POST (After Commit)'),
               yticks=(0, 25, 50, 75, 100))
        ax.spines[['top', 'right']].set_visible(False)
        ax.spines[['left', 'bottom']].set_linewidth(.65)
        ax.tick_params(axis='both', length=3, width=.65, labelsize=7.4)
        ax.grid(axis='y', color='#D9D9D9', linewidth=.55)
        ax.set_axisbelow(True)
        fig.suptitle('Effect of Commitment on\nAppropriate Resolution',
                     fontsize=9.2, weight='bold', y=.965)
        fig.legend(*ax.get_legend_handles_labels(), loc='lower center', bbox_to_anchor=(.5, .015),
                   frameon=False, ncol=3, fontsize=7, handlelength=2.4, columnspacing=1.3)

        def label(value, x, offset, align, suffix=''):
            ax.annotate(f'{float(value):.1f}%{suffix}', (x, value), xytext=offset,
                        textcoords='offset points', ha=align, va='center', fontsize=7.4,
                        bbox=dict(facecolor='white', edgecolor='none', pad=.45))

        # Concentric markers and shared labels keep tied observations at their true coordinates.
        label(rates['A'][0], 0, (8, 7), 'left')
        label(rates['PACT'][0], 0, (8, 3), 'left', ' (P, PACT)')
        label(rates['PACT'][1], 1, (0, 10), 'center')
        label(rates['P'][1], 1, (-7, -8), 'right', ' (A, P)')

        lower, upper = rates['P'][1], rates['PACT'][1]
        ax.plot((1.08, 1.12, 1.12, 1.08), (lower, lower, upper, upper),
                color=teal, linewidth=.8)
        ax.text(1.17, (lower + upper) / 2, f'{float(upper - lower):+.1f}\npercentage points',
                va='center', ha='left', color=teal, fontsize=7.1, weight='bold')

        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(OUTPUT.with_suffix('.pdf'), metadata={'CreationDate': None, 'ModDate': None})
        fig.savefig(OUTPUT.with_suffix('.png'), dpi=600)
        plt.close(fig)


if __name__ == '__main__':
    main()
