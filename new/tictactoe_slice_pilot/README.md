# Tic-Tac-Toe C × D pilot

This pilot implements step 1 of the slice discussion. It enumerates every legal
decision reachable from the empty board, evaluates each legal action with the
repository's exact minimax solver, and prepares a fixed panel for measuring a
real model's action distribution. It does not train a model or claim to measure
reasoning from action accuracy alone.

## Oracle enumeration

```sh
python new/tictactoe_slice_pilot/analyze.py build \
  --output new/tictactoe_slice_pilot/pilot_data \
  --discount 0.9 --per-category 32 --seed 42
```

The existing output has 5,478 reachable boards, 4,520 nonterminal decisions,
and 627 decisions after board symmetries are removed. The panel contains 128
symmetry-distinct decisions, 32 from each category:

| Category | Meaning | Full count | Canonical count |
|---|---|---:|---:|
| `immediate_win` | At least one move wins now; exact action values differ | 2,112 | 282 |
| `immediate_threat` | No immediate win; opponent has a one-move win threat; values differ | 936 | 127 |
| `non_immediate_split` | Values differ without either immediate condition | 467 | 68 |
| `flat` | All legal moves have the same exact value at discount 0.9 | 1,005 | 150 |

These are **structural descriptions**, not proofs of a model's cognitive
process. The exact-value spread is positive in 3,515 of 4,520 decision states.
At discount 1.0, 3,191 states have an outcome-value spread; the other 324
positive spreads at discount 0.9 distinguish only win/loss timing. Among
symmetry-distinct states, the top 20 by maximum action-value spread are all
`immediate_win`. The same holds for the top 20 under a hypothetical uniform
action policy. Neither ranking is a current-model result.

`pilot_data/oracle_states.jsonl` contains all action values and regrets.
`pilot_data/panel_oracle.jsonl` is the scoring key. The separate
`pilot_data/panel_requests.jsonl` contains the model-facing prompts and legal
moves, without oracle labels or category tags. The prompt text follows the
current Tic-Tac-Toe environment's compact reason-and-answer format.

## Measuring the actual model policy

Run a named checkpoint against `panel_requests.jsonl` with one fixed decoding
protocol, collecting repeated raw responses per board. The scorer accepts
one response per JSONL row:

```json
{"board":".........","response":"<reason>...</reason><answer>X(1,1)</answer>"}
```

It also accepts `{"board":".........","responses":["...","..."]}`.
Then score those outputs:

```sh
python new/tictactoe_slice_pilot/analyze.py score \
  --oracle-dir new/tictactoe_slice_pilot/pilot_data \
  --samples /path/to/model_responses.jsonl \
  --output /path/to/fresh_score_directory \
  --model-id checkpoint-name --temperature 0.6 \
  --min-valid-samples 8
```

For each board, `expected_oracle_regret_valid` is
`sum_a empirical_probability(a) * (max_b Q(b) - Q(a))`, conditional on
responses that parse as a single legal action. Invalid outputs are reported
separately and never assigned a canonical game regret. Only boards with at
least eight valid samples enter the ranking. Use the same model checkpoint,
prompt, temperature, and sample count across the panel; otherwise the
estimated decision distributions are not directly comparable. With finite
samples, close ranks have sampling uncertainty.

No model weights or Tic-Tac-Toe rollout responses are available locally in
this workspace, so `pilot_data/summary.json` deliberately says
`model_scored: false`. The current outputs establish the oracle side and the
fixed probe panel; a real-model C × D ranking requires those responses.

## SoC cluster probe

`probe.py` submits the fixed panel to a local OpenAI-compatible vLLM server.
`sbatch_probe.sh` starts and stops its own single-GPU server using the recorded
SoC `marshal-vllm09` environment, an H100-96 allocation, and the model path
passed to it. Defaults match the repository's Tic-Tac-Toe generation settings:
temperature 0.7, top-p 0.8, top-k 20, and a 600-token cap. The probe stores
the full requests, seeds, responses, completion statuses, model hash, and
source hashes. It writes `COMPLETE.json` only after all HTTP calls and scoring
finish. The source-hash check runs before GPU model loading.

The pilot and its oracle source files are committed on the
`codex/tictactoe-slice-pilot` Git branch. On the SoC login host, clone that
branch into a separate directory:

```sh
git clone --depth 1 --branch codex/tictactoe-slice-pilot \
  https://github.com/realidx/MARSHAL.git \
  /home/e/e1300530/MARSHAL-ttt-slice-pilot
```

To receive later pilot updates, run `git pull --ff-only` in that clone.
Submit a four-board smoke run from the login host:

```sh
cd /home/e/e1300530/MARSHAL-ttt-slice-pilot
sbatch --export=ALL,PILOT_LIMIT=4,PILOT_REPLICAS=2,PILOT_MIN_VALID_SAMPLES=2 \
  new/tictactoe_slice_pilot/sbatch_probe.sh \
  "$PWD" \
  /home/e/e1300530/models/Qwen3-4B-Instruct-2507 \
  /home/e/e1300530/ttt-slice-pilot-smoke-results
```

After checking the smoke result's `COMPLETE.json`, submit the full fixed
128-board panel with 16 independent draws per board:

```sh
sbatch --export=ALL,PILOT_LIMIT=0,PILOT_REPLICAS=16,PILOT_MIN_VALID_SAMPLES=8 \
  new/tictactoe_slice_pilot/sbatch_probe.sh \
  "$PWD" \
  /home/e/e1300530/models/Qwen3-4B-Instruct-2507 \
  /home/e/e1300530/ttt-slice-pilot-full-results
```

The run directory contains `probe/summary.json`, `probe/calls.jsonl`, and
`score/summary.json` plus `score/ranked.jsonl`. Rank estimates are conditional
on valid legal-action completions; invalid and truncated outputs are counted
separately. The base Qwen checkpoint is the initial-model measurement. A
later trained checkpoint can be passed as `MODEL_DIR` to measure how the
ranking changes during learning.
