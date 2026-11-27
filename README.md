# DASE7506 Final Project

This project studies how an LLM agent revises an in-progress plan when the user changes the goal. The protocol compares three continuation strategies from matched AppWorld checkpoints. A separate condition starts from the initial state with the revised goal. See [PLAN.md](PLAN.md) for the experiment protocol and [PROGRESS.md](PROGRESS.md) for observed results.

## Local setup

The bootstrap was verified with Python 3.11 on macOS arm64, AppWorld `0.1.3.post1` with data and database version `0.1.0`, and InterventionBench v1.1 at commit `7fe53126b93e8d3ef7e28bafbf8db6c6060e679e`. The AppWorld interventions JSONL has SHA-256 `4212365f457fda19dbb642888990e1dff2c63bb4a3724998d3ae2362a588a4c1`.

```bash
python3.11 -m venv .venv
.venv/bin/pip install 'appworld==0.1.3.post1'
mkdir -p .upstream .appworld
git clone https://github.com/jhn25/InterventionBench.git .upstream/InterventionBench
git -C .upstream/InterventionBench checkout --detach 7fe53126b93e8d3ef7e28bafbf8db6c6060e679e
.venv/bin/appworld install
.venv/bin/appworld download data --root "$PWD/.appworld"
```

The scorer reads the official benchmark files locally. Keep the simulator data and raw logs outside version control. The upstream data and papers are available from [InterventionBench](https://github.com/jhn25/InterventionBench), [AppWorld](https://github.com/StonyBrookNLP/appworld), the [InterventionBench paper](https://aclanthology.org/2026.findings-emnlp.698/), and the [AppWorld paper](https://aclanthology.org/2024.acl-long.850/).

## Checks

```bash
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
