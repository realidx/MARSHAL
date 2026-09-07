# BENAC-P complete semantic diagnosis

Use the existing remote vLLM 0.28 + hermes service. The client needs the
repository Python environment and numpy, without ROLL/Ray or a local GPU.

```bash
bash examples/benac_p/run_full_diagnose.sh
```

This now runs **semantic B, P given a judgment, B→P, P→B, and complete model
interaction trajectories**, using deterministic rational partners. The model
outputs only `SUBMIT_JUDGMENT(possible_preferences=[...])` or
`SUBMIT_ACTION(action_index=...)`, preceded by:

> Briefly reason about the task before submitting your answer.

No probability, utility, Q, ranking or plan output is requested. There is no
sentence or word quota. The total completion cap remains **1024 tokens**,
including reasoning and tool arguments; auto tool calling is retained.

Defaults: `Qwen/Qwen3-4B-Instruct-2507`, `http://localhost:8000/v1`, four workers,
seed 20000. Use the same service/model environment variables as before:

```bash
BENAC_P_VLLM_BASE_URL=http://your-server:8000/v1 \
VLLM_SERVED_MODEL_NAME=your-served-model-id \
bash examples/benac_p/run_full_diagnose.sh
```

`BENAC_P_VLLM_API_KEY` supplies authentication and is not saved in artifacts.
Other overrides: `PYTHON_BIN`, `BENAC_DIAGNOSE_OUTPUT_DIR`,
`BENAC_DIAGNOSE_MAX_TOKENS`, `BENAC_DIAGNOSE_WORKERS`, `BENAC_DIAGNOSE_SEED`,
`BENAC_DIAGNOSE_GAMES` (an even number of matched bundles, at least two).

Default: **12 matched bundles / 36 games**. Every bundle contains unknown
relevant preferences, known preferences, and unknown irrelevant preferences.
Six bundles are discovery; six are confirmation. There are 288 static requests
and at most 504 additional requests; identical action/response branches are
reused across interventions. Exact counts and fingerprints are exported.

```bash
# CPU certification and task export; no model requests.
bash examples/benac_p/run_full_diagnose.sh --export-only

# Complete synthetic oracle test. Not a real-model result.
bash examples/benac_p/run_full_diagnose.sh --oracle-check

# Continue an interrupted run; keep all original parameters unchanged.
BENAC_DIAGNOSE_OUTPUT_DIR=/path/to/run bash examples/benac_p/run_full_diagnose.sh --resume

# Rescore saved model outputs without contacting the service.
BENAC_DIAGNOSE_OUTPUT_DIR=/path/to/run bash examples/benac_p/run_full_diagnose.sh --score-only
```

A normal invocation creates a fresh timestamped directory under
`runs/benac_semantic_diagnose/`. Do not reuse an old stochastic output directory.
`--response-protocol json_action` provides an action/judgment-only JSON control
in a separate output directory.

Read `report.md` and `summary.json` for the four blocks, both four-cell tables,
format coverage, matched controls and confidence intervals. `scores.json`
contains per-branch evidence/judgment measurements and both updater-repair
contrasts. `rollouts.json` contains all hidden-configuration trajectories,
commitments and terminal outcomes. `protocol_summary.json` reports completion
length, reasoning coverage and truncation; raw outputs remain in `answers.json`.
Invalid/truncated outputs are not strategic PASS actions. Incomplete branch
sets are not silently renormalized. Manifest and request hashes guard resume.

**Scope:** selected three-player, three-turn BENAC subgames with a public
stage-specific offer catalogue. Every proposal uses the original legal binding
commitment engine. Partners' terminal optimality is certified over all allowed
future ego choices using only their own preferences. This is not a population
estimate for unrestricted BENAC, a long-horizon benchmark, or transfer evidence.
All model-visible information needed for scoring, including equal-frequency
joint configurations and deterministic tie-breaking, is stated in the prompt.

Full definitions and caveats: [semantic diagnosis protocol](../../new/semantic_diagnose_protocol.md).

## Legacy experiments

- `run_stochastic_diagnose.sh`: previous four-block probability-output experiment.
  Its `--extended` probes remain available; they are not part of the semantic suite.
- `run_menu_diagnose.sh`: old 11-call menu-only pilot.
- [Old stochastic protocol](../../new/full_diagnose_protocol.md): historical metrics
  and interpretation; do not combine its results with the semantic suite.

The native unrestricted game runner remains available with
`python -m benac_p.cli --menu --self-play vllm --json`. It is separate from this
controlled diagnostic protocol and does not automatically use these certified
partner rules.
