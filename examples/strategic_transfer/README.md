# Strategic interaction transfer proof of concept

This directory implements the first evaluation stage without training a new
model.  It compares `Qwen/Qwen3-4B` with
`nics-efc/MARSHAL-Generalist-Qwen3-4B` in two held-out evaluations:

1. a deterministic persistent-source trust diagnostic; and
2. Cooperate to Compete (C2C), with one focal checkpoint changed and three
   frozen heterogeneous counterparties.

The screening target is 50 paired episodes/games per condition. Treat the
result as a go/no-go signal, not a definitive estimate. A positive screen should
be repeated with at least 200 pairs.

## 1. Trust-calibration diagnostic

Generate the suite once. Both checkpoints must consume the same file.

```bash
python -m examples.strategic_transfer.trust_calibration generate \
  --output runs/trust_calibration/suite.jsonl \
  --num-episodes 50 --num-rounds 12 --seed-base 26042026
```

A dependency-free smoke run checks generation, persistence, and scoring:

```bash
python -m examples.strategic_transfer.trust_calibration run \
  --suite runs/trust_calibration/suite.jsonl \
  --output runs/trust_calibration/oracle.jsonl --scripted oracle
```

For a model served through an OpenAI-compatible endpoint:

```bash
python -m examples.strategic_transfer.trust_calibration run \
  --suite runs/trust_calibration/suite.jsonl \
  --output runs/trust_calibration/base.jsonl \
  --api-base http://127.0.0.1:8000/v1 --api-key EMPTY \
  --model qwen3-4b-focal
```

Restart the server with the MARSHAL checkpoint and write `treatment.jsonl`.
Rescore and compare the raw files without rerunning inference:

```bash
python -m examples.strategic_transfer.trust_calibration compare \
  --base-input runs/trust_calibration/base.jsonl \
  --treatment-input runs/trust_calibration/treatment.jsonl \
  --delta-drop-margin 0.20 \
  --output runs/trust_calibration/paired-trust-comparison-v2.json
```

Version 2 reports stable-adversary identification, Delta switch recognition,
post-switch recall of both adversaries, paired Delta-reliability trajectories,
and behavioral reliance on Delta. The 0.20 drop margin is fixed prospectively
for future runs; for run 744718 it is explicitly post-hoc. The old
`unreliable_source_identification_accuracy` remains under `defective_metrics`
for provenance only and must not support conclusions. Raw prompts, responses,
reports, and feedback are retained in each JSONL row.

## 2. Matched C2C evaluation

The adapter is pinned to C2C commit
`2f7eb4a163d21e139a3ea8b9f7d625b470594f00`. The upstream README currently
advertises an unavailable organization URL, so setup uses the authors' live
repository.

```bash
bash examples/strategic_transfer/setup_c2c.sh
```

Prepare a single paired plan. This balances focal commander and secret-objective
type while keeping every pair's board, objective, seat, and counterparties fixed:

```bash
python -m examples.strategic_transfer.c2c_paired prepare \
  --output runs/c2c_marshal_poc/plan.json \
  --num-pairs 50 --num-boards 50 --seed-base 26042026 \
  --counterparty-model openrouter/openai/gpt-5.2 \
  --counterparty-model xai/grok-4-1-fast-non-reasoning \
  --counterparty-model gemini/gemini-3.1-flash-lite-preview
```

Serve the base checkpoint locally. C2C uses JSON-mode chat completions, so the
server must expose a working chat template:

```bash
vllm serve Qwen/Qwen3-4B \
  --served-model-name qwen3-4b-focal \
  --port 8000 --max-model-len 32768 \
  --generation-config vllm --seed 26042026
```

With provider keys set for the three counterparties, run the base condition:

```bash
OPENAI_API_BASE=http://127.0.0.1:8000/v1 OPENAI_API_KEY=EMPTY \
python -m examples.strategic_transfer.c2c_paired run-condition \
  --plan runs/c2c_marshal_poc/plan.json --condition base \
  --focal-model openai/qwen3-4b-focal --num-workers 1
```

Restart vLLM with `nics-efc/MARSHAL-Generalist-Qwen3-4B`, preserving the served
name, generation settings, and all other arguments; then run with
`--condition treatment`. Before the screen, run the two-pair infrastructure
preflight with one worker and the frozen smoke plan. Inspect the first
`error.json`, vLLM log, and Slurm output after any failure; an operational
failure is not a scientific null. `DEBUG_LLM_CALLS=true` preserves every C2C
prompt and response.

Summarize the primary outcome:

```bash
python -m examples.strategic_transfer.c2c_paired summarize \
  --base-dir runs/c2c_marshal_poc/base \
  --treatment-dir runs/c2c_marshal_poc/treatment \
  --output runs/c2c_marshal_poc/paired_summary.json
```

The preregistered primary metric is focal secret-objective completion by the
50-round horizon. The summary includes the paired completion-rate difference,
discordant-pair counts, net paired wins, and completion/error-rate balance.
Treat about +6 percentage points or at least three net paired wins as promising
for expansion, provided completion and error rates differ by no more than five
percentage points between conditions. Run C2C's released analysis pipeline
separately for negotiation follow-through, support exchange, partner diversity,
negotiation–attack separation, deception, and offer/counteroffer mechanisms.
Those metrics explain the primary outcome; they do not redefine success.

## Interpretation

| C2C result | Interpretation given the trust diagnostic |
|---|---|
| MARSHAL positive | Transfer exists, but likely through planning, tactics, negotiation conventions, or stable-partner discrimination—not adaptive trust calibration. |
| null | Null/null outcome: no evidence that the released checkpoint transfers to persistent mixed-motive interaction. |
| MARSHAL negative | The post-training may be mismatched to this richer interaction setting; inspect validity and behavioral mechanisms before concluding harm. |

Do not train a new model yet. A null result does not test a tailored social-game
curriculum; additional social-game training is a later-stage experiment only
after this checkpoint screen.
