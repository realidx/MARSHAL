# NUS single-GPU outcome rollout smoke test

This is an inference-only entrypoint. It starts one local vLLM server, runs
three complete-game attempts (two 2-player games and one 3-player game), saves
requests and native replay checks, then stops its own server. No training runs.
Existing rollout interfaces are unchanged.

## Run on NUS

Log in through the jump host, update this Git branch, and submit from the repo root:

```bash
ssh -J e1300530@stujump.comp.nus.edu.sg e1300530@xlogin.comp.nus.edu.sg
cd /home/e/e1300530/MARSHAL
git fetch origin
git switch --track origin/codex/outcome-rollout-nus-1gpu
git pull --ff-only
sbatch examples/outcome_selfplay_nus/sbatch_smoke.sh
```

If the local branch already exists, use `git switch codex/outcome-rollout-nus-1gpu`.
Do not discard local changes to switch branches.

The Slurm resource selection and environment paths reuse the recorded NUS
`examples/item_game/sbatch_probe_vllm_native_reason.sh` setup:

- One `gpu:h100-47:1` allocation; scheduler GPU visibility is preserved.
- Python: `/home/e/e1300530/tmp/marshal-vllm09/bin/python`.
- Model: `/home/e/e1300530/models/Qwen3-4B-Instruct-2507`.
- Hermes tool parser, context 8192, response limit 2048, request timeout 180 s.
- One game at a time, one rollout per reset, vLLM memory utilization 0.40.

These are historical paths, checked for existence when the job starts. Override
them if needed through `OUTCOME_PYTHON` and `OUTCOME_MODEL` before `sbatch`.
`bash examples/outcome_selfplay_nus/run_smoke.sh --help` lists other overrides.
The launcher rejects more than one visible GPU and binds only localhost. It
does not install packages, modify the environment, or stop existing services.

## Outputs and interpretation

Slurm stdout is `slurm-outcome-rollout-smoke-<jobid>.out`. The launcher prints
`OUTCOME_RUN_DIR`, a unique directory under `runs/outcome_selfplay_nus/` containing:

- `server_manifest.json`, `models.json`: environment and model-service identity.
- `server.log`, `client.log`: inference and rollout logs.
- `rollout/summary.json`, plus detailed episode and request records.
- The verified runtime source used by that run.

A completed shell command alone does not establish success: inspect the summary
for terminal games, request failures, invalid calls, retries, and replay checks.
Incomplete games have no terminal outcome reward. The runtime allows
one retry for invalid tool output or truncation, charging -0.1 per such failure;
transport timeouts are recorded separately without that penalty. Player terminal
outcome and format penalty remain separately recorded. HTTP rollouts are for
integration testing, not token/logprob-ready training batches.

## Readable v3 prompt

The active NUS launcher uses `runtime_v3.tar.gz`. `selfplay_prompt.py` follows the
current B/P readable interface: named players, goals and commitments; natural
language public history; separate binding commitments and proposed additions;
private investigation answers with explicit ownership; remaining proposal order.
The model calls OFFER / INVESTIGATE / PASS / ACCEPT / REJECT directly. OFFER
arguments contain only new named commitments. The adapter checks the exact legal
combination and converts it back to the unchanged native target vectors.

Self-play retains binary AND linear goal completion, the actual two-value or
three-value preference prior, and only the player's own outcome objective. It
supplies no B/P gold, belief answer, teacher policy or altruistic tie-break.
Invalid-call retries and penalties are unchanged. Old v1/v2 records remain
replayable; v3 records identify the readable prompt and preserve actual tool schemas.

`bp_display.py` freezes only the pure Names, action-tools and visible-fact/history
helpers from `training/b_sft/social_named_probe.py` and `social_prompt.py`.
Per-source SHA256 hashes are recorded in that file. This reuses the reviewed B/P
presentation without importing the mutable teacher or modifying B/P files.
`rollout.py` is the isolated v3 collector based on the frozen v2 implementation.

## Frozen dependency reuse and local checks

The unchanged `runtime_v2.tar.gz` came from the existing
`runs/outcome_selfplay_screen/outcome_rollout_runtime_v2.tar.gz`. That directory
is Git-ignored. The snapshot provides all shared environment imports needed by a
remote checkout; rollout does not call teacher solving or use B/P gold.

`build_runtime.py` builds v3 deterministically from that frozen base and only the
three reviewed files `rollout.py`, `selfplay_prompt.py`, `bp_display.py`. It never
reads the concurrent B/P working tree. After editing these sources, run with a
Python >= 3.10 environment containing numpy:

```bash
python examples/outcome_selfplay_nus/build_runtime.py
python examples/outcome_selfplay_nus/test_readable_runtime.py
bash -n examples/outcome_selfplay_nus/run_smoke.sh examples/outcome_selfplay_nus/sbatch_smoke.sh
```

The CPU checks use fake tool completions over all 24 reset configurations, replay
native terminal rewards, verify named-action conversion and privacy boundaries,
and exercise an invalid-output retry and penalty. They never contact a model.
They do not establish real-model comprehension or vLLM tool-parser compatibility.

`unpack_runtime.py` verifies the archive and each manifested source. Each run
unpacks into a fresh directory. Keep the old v2 archive for reproducibility; the
new launcher explicitly selects v3. Outputs and GPU settings are unchanged.

## Diagnose missing explanations without replaying full games

```bash
sbatch --export=ALL,OUTCOME_REASONING_PROBE=1 examples/outcome_selfplay_nus/sbatch_smoke.sh
```

This opt-in mode reuses the same single-GPU server launcher but runs 44 fixed
visible-state requests, no environment transitions, training, retries or rewards.
It saves full HTTP response bodies in `reasoning_probe/samples.jsonl`, along with
an aggregate `summary.json` under the printed run directory.

Four self-play states (INVESTIGATE, OFFER, ACCEPT, PASS contexts from job 846757)
are each tested at two paired seeds under five conditions: original v3 request;
remove only the protocol-penalty sentence; replace only the system message with
the B/P system message; append an explicit 1–3-sentence explanation request;
change only temperature from 0.7 to 0.8. Four B/P control requests come from
job 846561 (one B and one P state at two seeds). B/P controls retain their 1024
token budget and temperature 0.8; they are not matched task-content comparisons.
The inputs contain only already player-visible messages and tools, no teacher
answers or hidden worlds. The request file freezes the exact inputs for review.

Compare both explanation coverage and completed tool submissions: extra prose
that hits the token limit is not a successful repair. The script's submission
metric checks tool name/count and non-truncation, not full argument legality or
reasoning correctness. Two samples per state/condition give a small diagnostic,
not a statistically conclusive estimate. No arm changes the active v3 prompt.

Offline input validation (no model calls):

```bash
python examples/outcome_selfplay_nus/reasoning_probe.py --check-only
```
