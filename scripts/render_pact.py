"""Render the integrated IEEE manuscript from frozen result tables."""

import csv
import json

from scripts.render_tables import OUTPUT, RESULTS, table

ARMS = ('A', 'P', 'PACT')


def load(folder, filename):
    with (RESULTS / folder / f'{filename}.csv').open() as handle:
        return list(csv.DictReader(handle))


def metric(row, key, denom=None):
    n = int(row[denom or key + '_n'])
    return f"{row[key]}/{n}" if n else '--'


def ci(row):
    return f"{float(row['delta_pp']):+.1f} [{float(row['low_95']):.1f}, {float(row['high_95']):.1f}]"


def usd(value):
    return int(value) / 1_000_000_000


def put(name, *parts):
    (OUTPUT / f'{name}.tex').write_text('\n\n'.join(p.strip() for p in parts) + '\n')


def write_historical():
    data = {(r['cohort'], r['arm']): r for r in load('harness_v5', 'summary')
            if r['stratum'] == 'all' and r['cohort'] in ('historical_40', 'new_families')}
    h, new = 'historical_40', 'new_families'
    rows = []
    for arm in ('A', 'B', 'C', 'R', 'C+', 'C++', 'C5', 'G5', 'D'):
        row = data[h, arm]
        fresh = data.get((new, arm))
        rows.append([arm, metric(row, 'final', 'n'), metric(row, 'strict', 'n') if arm != 'D' else '--',
                     metric(row, 'supervisor_violation', 'known_violation_n'),
                     metric(row, 'application_violation', 'known_violation_n'),
                     metric(fresh, 'final', 'n') if fresh else '--',
                     metric(fresh, 'strict', 'n') if fresh and arm != 'D' else '--'])
    put('tables', table('tab:history', 'Frozen historical outcomes, with the independent nine-family confirmation '
                        'shown separately. D starts from the revised goal in the initial world.',
                        'lrrrrrr', ['Arm', 'Final', 'Strict', 'Supervisor', 'Application', 'New final', 'New strict'],
                        rows, wide=True))
    pairs = {(r['first'], r['second']): r for r in load('harness_v5', 'paired') if
             r['stratum'] == 'all' and r['cohort'] == h}
    a, b = data[h, 'C+'], data[h, 'C5']
    diff = pairs['C5', 'C+']
    diag = json.loads((RESULTS / 'harness_v5/diagnosis.json').read_text())
    audit = {r['arm']: r for r in load('harness_v5', 'sensitivity')}
    total = sum(int(r['n']) for r in data.values())
    assert total == 405
    original, rescored = ('/'.join(audit[arm][key] for arm in ('A', 'C', 'C+', 'C5', 'G5'))
                          for key in ('original', 'revised'))
    put('results', r'\subsection{Historical results}',
        f"Table~\\ref{{tab:history}} summarizes {total} frozen historical branches. C+ fell back in "
        f"{metric(a, 'fallback', 'n')} after a first-round failure on {diag['first_failed']} families. "
        f"Decimal normalization and merging consistent references rescued {diag['recovered_by_normalization']} "
        f"of the {diag['legacy_fallback']} fallbacks under original checks. Full C5 validation retained "
        f"{diag['c5_full']} complete and {diag['c5_partial']} partial states in the replay. In actual "
        f"continuations C5 produced {b['full']} full and {b['partial']} partial states. Its strict success "
        f"was {metric(b, 'strict', 'n')}, equal to C+ with paired difference {ci(diff)} percentage points "
        f"({diff['first_only']} win and {diff['second_only']} loss). The contrasts to C and A were "
        f"{ci(pairs['C5','C'])} and {ci(pairs['C5','A'])} points.",
        'Historical natural replay included 689 successful requests, of which 385 had unverified labels. '
        'All 35 observed positives were supervisor submissions, and neither guard detected them. G5 identified '
        'six of 40 isolated boundary positives and correctly blocked a draft send in a simulator control. '
        'In V5 formal execution it made 223 checks with no blocks. In return case 737, the exact rule '
        'covered the original order while six returns on other orders reached the simulator.',
        'An independent audit of five common Drop failures found a notification-filter inconsistency in '
        f"cases 267 and 272 and mismatched return checks in case 737. The audit changed historical strict "
        f"counts for A/C/C+/C5/G5 from {original} to {rescored} of 40. "
        'The frozen scores remain primary and the audit is reported independently.')
    return total, a, b


def write_pact():
    summary = {(r['stratum'], r['boundary'], r['method']): r
               for r in load('pact', 'summary') if r['stage'] == 'formal'}
    pairs = {(r['stratum'], r['boundary'], r['second']): r for r in load('pact', 'paired')}
    budget = json.loads((RESULTS / 'pact/budget.json').read_text())
    rows = load('pact', 'branch_metrics')
    indexed = {(int(r['intervention_id']), r['boundary'], r['method']): r for r in rows if r['stage'] == 'formal'}
    n = sum(r['status'] == 'scored' for r in indexed.values())
    post_contrast = pairs['all', 'POST', 'P']
    metrics = ('arr', 'disposition', 'report', 'required_ask', 'unnecessary_ask', 'unauthorized_repair',
               'post_violation', 'independent', 'priority', 'retained')
    top = []
    for boundary in ('PRE', 'POST'):
        for arm in ARMS:
            row = summary['all', boundary, arm]
            top.append([boundary, arm, *(metric(row, m) for m in metrics),
                        row['model_calls'], f"{usd(row['peak_nano_usd']):.3f}"])
    tab = table('tab:pact', 'Formal PACT outcomes. Entries are counts over applicable denominators. '
                'Costs are total peak-price USD. Disp. denotes disposition, Extra an unnecessary question, and Unauth. an unauthorized repair.',
                'll' + 'r'*12,
                ['Side', 'Arm', 'ARR', 'Disp.', 'Report', 'Ask', 'Extra', 'Unauth.',
                 'Viol.', 'Indep.', 'Order', 'Retain', 'Calls', 'USD'], top, wide=True)
    tab = tab.replace(r'\small', r'\small\setlength{\tabcolsep}{3pt}')
    strata = [['Official' if s == 'natural' else 'Controlled', b,
               *[metric(summary[s, b, a], 'arr') for a in ARMS]]
              for s in ('natural', 'controlled') for b in ('PRE', 'POST')]
    st = table('tab:pactstrata', 'ARR by source of the revised instruction.', 'llrrr',
               ['Revision', 'Boundary', *ARMS], strata)
    pair_rows = [[f'PACT vs {a}', b if b != 'POST_minus_PRE' else 'Interaction',
                  pairs['all', b, a]['wins'], pairs['all', b, a]['losses'], ci(pairs['all', b, a])]
                 for a in ('P', 'A') for b in ('PRE', 'POST', 'POST_minus_PRE')]
    ct = table('tab:pactpair', 'Matched ARR differences with family-bootstrap intervals in percentage points. '
               'The interaction compares the two boundary contrasts.',
               'llrrr', ['Contrast', 'Side', 'W', 'L', r'Diff. [95\% CI]'], pair_rows)
    ct = ct.replace(r'\small', r'\small\setlength{\tabcolsep}{3pt}')

    def cell(boundary):
        return ', '.join(f"{a} {metric(summary['all', boundary, a], 'arr')}" for a in ARMS)

    def outcomes(n, boundary):
        return ', '.join(f"{a} {'passed' if indexed[n, boundary, a]['arr']=='1' else 'failed'}" for a in ARMS)

    post = {a: summary['all', 'POST', a] for a in ARMS}
    sensitivity = {a: sum(int(r['reference_sensitivity_arr']) for r in load('pact','reference_sensitivity')
                         if r['boundary'] == 'POST' and r['method'] == a) for a in ARMS}
    asks = ', '.join(f"{metric(post[a], 'required_ask')} for {a}" for a in ARMS)
    coop = summary['controlled', 'POST', 'PACT']
    gate = [summary['all', b, 'PACT'] for b in ('PRE', 'POST')]
    checked, rejected, apparent = (sum(int(row[k]) for row in gate) for k in
                                   ('gate_checked', 'gate_rejected', 'declared_scope_candidate_blocks'))
    stage = budget['pact_by_stage']['formal']
    money = lambda amount: r'\$' + f'{usd(amount):.3f}'
    plot = r"""\begin{figure}[t]
\centering
\includegraphics[width=\columnwidth]{figures/commitment_arr.pdf}
\caption{Appropriate resolution across the two commit boundaries. Each point summarizes 12 matched task families. The bracket shows the observed POST difference between PACT and Procedure Prompt.}
\label{fig:commit-arr}
\end{figure}"""
    put('case_analysis', r'\subsection{Formal outcomes}', plot, tab, st, ct,
        f"All {n} formal branches were scored. Figure~\\ref{{fig:commit-arr}} shows an observed tie "
        "between PACT and Procedure Prompt in PRE. "
        f"PRE ARR was {cell('PRE')}. POST ARR was {cell('POST')}. "
        f"The POST contrast between PACT and Procedure Prompt was "
        f"{float(post_contrast['delta_pp']):+.1f} percentage points "
        f"(95\\% family-bootstrap interval [{float(post_contrast['low_95']):.1f}, "
        f"{float(post_contrast['high_95']):.1f}]). Among discordant pairs, "
        f"{post_contrast['wins']} favored PACT and {post_contrast['losses']} favored Procedure Prompt. "
        f"The two-sided exact McNemar test gave $p={post_contrast['exact_mcnemar_unadjusted']}$, "
        "which does not meet the conventional 0.05 threshold. The bootstrap interval resamples "
        "the observed families and excludes zero. The exact test conditions on the five discordant pairs. "
        "We interpret the difference as exploratory. "
        f"Table~\\ref{{tab:pactpair}} reports the PRE contrast, the comparison with Native, and the interaction.",
        f"Accepting object IDs verified against actual tool receipts changed POST ARR to "
        f"{sensitivity['A']}/12 for A and {sensitivity['P']}/12 for P, with PACT at {sensitivity['PACT']}/12. "
        "The main analysis retains the frozen rule requiring the displayed receipt reference.",
        f"The required POST decision counts were {asks}. PACT completed independent work in "
        f"{metric(coop,'independent')} applicable controlled POST branches and met the priority and dependency "
        f"rubric in {metric(coop,'priority')}. Across both boundaries its gate checked {checked} API proposals and "
        f"rejected {rejected}. Of these, {apparent} matched an eventual work scope. Their validity also depends "
        'on the local scheduling context, so the logs do not support a verified false-positive rate. '
        'A controlled simulator test verified that rejection left the state unchanged and independent writes proceeded.',
        'PACT escalated more often and completed fewer independent POST tasks. '
        f"Independent work was completed in {metric(post['A'],'independent')} branches for Native A, "
        f"{metric(post['P'],'independent')} for Procedure P, and {metric(post['PACT'],'independent')} for PACT. "
        'Each method had zero monitored unauthorized repairs across 12 POST branches. '
        'The difference concerns the measured resolution of committed actions, including reports and '
        'decision requests that PACT can log automatically. The experiment does not isolate the effect of automation.',
        f"Formal inference returned {stage['receipts']} receipts at an estimated peak cost of "
        f"{money(stage['peak_nano_usd'])}. Including both pilot rounds and any open PACT reservations, "
        f"the extension occupied at most {money(budget['pact_occupied_upper_nano_usd'])} of its "
        f"{money(budget['pact_limit_nano_usd'])} ceiling. The full project occupied at most "
        f"{money(budget['project_occupied_upper_nano_usd'])} of its original ten-dollar ceiling.",
        r'\subsection{Boundary cases}',
        'Case 244 retains a confirmed Venmo payment and withdraws the pending text acknowledging it. '
        f"In PRE the text is uncommitted ({outcomes(244,'PRE')}). In POST the real SMS receipt establishes a send, "
        f"making a report and an authorization request applicable ({outcomes(244,'POST')}). The payment remains "
        'valid on both sides.',
        'Case 118 withdraws a text, requires permission for a correction if already sent, and asks for two '
        'independent notes in order. An approval-gated third note must remain pending. '
        f"In POST, {outcomes(118,'POST')} under the primary receipt-reference rule. "
        'The score requires both independent notes and coherent escalation. Procedure P completed both notes '
        'and cited the committed SMS ID. The alternative-reference check credits that path.',
        'Case 300 demonstrates a controller failure. In PRE the chair was already in the cart, but the '
        'assessment added a new cart task and the gate let it add a second chair. The quantity correction '
        'was outside the authorized queue, so the final cart remained wrong. A matching endpoint and object '
        'therefore provided insufficient evidence that the operation was still needed. In contrast, the POST '
        'alarm case 32 provided an exact identifier and explicit repair authorization, which PACT used to '
        'delete only the newly created alarm before writing the independent note.')
    return [metric(post[a], 'arr') for a in ARMS], ci(pairs['all','POST','P'])


def main():
    total, cp, c5 = write_historical()
    (native, prompt, pact), effect = write_pact()
    put('abstract',
        f"A mid-task revision can arrive before a tool request commits or after its effects persist. "
        f"We first analyze {total} historical AppWorld branches across 49 task families. More tolerant "
        f"intent and evidence validation reduces complete fallback from {metric(cp,'fallback','n')} to "
        f"{metric(c5,'fallback','n')} in the historical cohort, with strict success unchanged at "
        f"{metric(c5,'strict','n')}. We then run 72 branches in matched PRE and POST worlds around a verified "
        'tool submission, reusing 12 historical families. The PACT controller can report effects and seek '
        'authorization automatically while scheduling independent work. POST Appropriate Resolution Rate is '
        f"{pact} for PACT, {prompt} for the full procedural prompt, and {native} for native continuation. "
        f"The observed paired difference is {effect} percentage points (estimate and 95\\% bootstrap interval). "
        'The results describe complete harnesses in a small matched sample.')
    put('conclusion', r'\section{Conclusion}',
        'Tolerant parsing and local evidence checks stabilized the historical intent state, while strict '
        'success remained unchanged against C+. The follow-on evaluation makes one real commit observable '
        f"and then supplies the same revision. PACT achieved {pact} appropriate POST resolutions versus "
        f"{prompt} for the procedure prompt, with a paired difference of {effect} points. The estimate is "
        'specific to the sampled families, model, and observable authorization conditions. PACT also completed '
        'less independent POST work. Commit-boundary pairing makes it possible to evaluate both the handling '
        'of a committed effect and the work that continues around it.')


if __name__ == '__main__':
    main()
