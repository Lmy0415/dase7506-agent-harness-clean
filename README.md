# DASE7506 Final Project

This project studies how an LLM agent revises an in-progress plan when the user changes the goal. The protocol compares three continuation strategies from matched AppWorld checkpoints. A separate condition starts from the initial state with the revised goal. See [PLAN.md](PLAN.md) for the experiment protocol and [PROGRESS.md](PROGRESS.md) for observed results.

## Local setup

The bootstrap was verified with Python 3.11 on macOS arm64, AppWorld `0.1.3.post1` with data and database version `0.1.0`, and InterventionBench v1.1 at commit `7fe53126b93e8d3ef7e28bafbf8db6c6060e679e`. The AppWorld interventions JSONL has SHA-256 `4212365f457fda19dbb642888990e1dff2c63bb4a3724998d3ae2362a588a4c1`.

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
mkdir -p .upstream .appworld
git clone https://github.com/jhn25/InterventionBench.git .upstream/InterventionBench
git -C .upstream/InterventionBench checkout --detach 7fe53126b93e8d3ef7e28bafbf8db6c6060e679e
.venv/bin/appworld install
.venv/bin/appworld download data --root "$PWD/.appworld"
```

The scorer reads the official benchmark files locally. Keep the simulator data and raw logs outside version control. The upstream data and papers are available from [InterventionBench](https://github.com/jhn25/InterventionBench), [AppWorld](https://github.com/StonyBrookNLP/appworld), the [InterventionBench paper](https://aclanthology.org/2026.findings-emnlp.698/), and the [AppWorld paper](https://aclanthology.org/2024.acl-long.850/).

## Checks

```bash
.venv/bin/python -m pytest -q tests
IPYTHONDIR="$PWD/.appworld/ipython" .venv/bin/python scripts/calibrate_alarm.py
```

This scripted simulator control uses task `31dc501_1`, InterventionBench row `386`. It writes local evidence to `artifacts/raw/alarm_calibration.json` without calling a model.

The paid diagnostic below lets DeepSeek work on the same task with the standalone revised goal and records its actual tool calls and score. It is separate from the pilot and formal experiment.

```bash
IPYTHONDIR="$PWD/.appworld/ipython" .venv/bin/python -m scripts.model_alarm
```

To verify the DeepSeek credential and native function calling, set `DEEPSEEK_API_KEY` locally in `.env` or the environment, then run the following paid check if needed. Every invocation uses the shared project budget ledger in `artifacts/raw/api_costs.jsonl`.

```bash
.venv/bin/python -m scripts.check_deepseek
```

## Candidate pools and checkpoint checks

```bash
.venv/bin/python scripts/build_candidates.py
IPYTHONDIR="$PWD/.appworld/ipython" .venv/bin/python -m scripts.check_shared_checkpoint
```

The candidate builder uses seed `7506`, holds out the two diagnostic families, and assigns each remaining family to one split and one stratum. `protocol/candidate_index.jsonl` records the ordered identifiers, and `protocol/candidate_census.json` gives the full census. `protocol/candidates.jsonl` contains local task text and evaluator references and is regenerated from the pinned upstream data. Pool membership precedes prefix screening and eligibility decisions.

The second checkpoint check commits a retained text-message deletion on task `771d8fc_1`, then exports the world before the pending voice-message deletion. Two separate worlds restore the same checkpoint and transcript. An isolated probe deletes the voice message while the clean world still retains it. The script writes the observations and private checkpoint to `artifacts/raw/` and `artifacts/checkpoints/`.

## Matched diagnostic and annotated prefix screening

```bash
IPYTHONDIR="$PWD/.appworld/ipython" .venv/bin/python -m src.runner
IPYTHONDIR="$PWD/.appworld/ipython" .venv/bin/python -m src.runner --intervention 487 --prefix-only
```

The first command runs the separate alarm diagnostic. The second screens an annotated pilot candidate without running suffixes. Both call DeepSeek and use the project ledger. To resume a confirmed prefix, pass its printed directory as `--resume-prefix` with the same `--intervention`. The runner skips scored branches and keeps failed attempts as separate traces. `src/annotations.py` contains the reviewed candidate rules for effect observation and retention scoring.

## Batch execution and analysis

```bash
IPYTHONDIR="$PWD/.appworld/ipython" .venv/bin/python -m src.batch
.venv/bin/python -m src.analyze --pilot
.venv/bin/python -m src.formal freeze-settings
IPYTHONDIR="$PWD/.appworld/ipython" .venv/bin/python -m src.formal screen
.venv/bin/python -m src.formal freeze-manifest
IPYTHONDIR="$PWD/.appworld/ipython" .venv/bin/python -m src.formal run
.venv/bin/python -m src.analyze
```

The two freeze commands run once for this protocol. Screening and execution resume from saved state. The manifest locks the case IDs, prefix checksums, execution order, and D subset before any formal suffix runs. Analysis preserves a row for each expected branch and writes sanitized per-branch metrics and family-paired summaries under `results/`. Files beneath `artifacts/raw/` remain local.

## Paper and results

- [Compiled IEEE paper](paper/report.pdf)
- [Overleaf ZIP](deliverables/overleaf_project.zip)
- [Chinese walkthrough](docs/PROJECT_WALKTHROUGH_ZH.md) and [verification checklist](docs/FINAL_CHECKLIST.md)
- [Formal per-branch metrics](results/branch_metrics.csv), [family-paired contrasts](results/paired.csv), and [costs](results/cost_breakdown.csv)

The local analysis and build can run from the saved evidence without any model calls.

```bash
.venv/bin/python -m src.analyze
.venv/bin/python scripts/audit_retention.py
.venv/bin/python scripts/render_tables.py
.venv/bin/python scripts/build_paper.py
```

The manuscript was rebuilt using Tectonic 0.17.0 and IEEEtran 1.8b. For a local Tectonic cache without IEEEtran, place `IEEEtran.cls` and `IEEEtran.bst` from the [CTAN package](https://ctan.org/pkg/ieeetran) under `.upstream/latex/IEEEtran/`. For a standard TeX Live installation, use `scripts/build_paper.py --engine latexmk`. The source archive uses Overleaf's standard IEEEtran class, and its extracted source was compiled locally. Upload it through New Project → Upload Project and select `main.tex`. Author names, student IDs, and affiliations are marked for completion.
