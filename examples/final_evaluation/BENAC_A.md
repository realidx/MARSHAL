# BENAC package A, fixed Q0 opponents

This release implements `[M,Q0,Q0]`, with M = Q0, SP-only step69, BP-only step139, Mixed step59. Checkpoints are fixed before observing A results; they were already examined on CalBench and are not independently selected on A. Different training budgets must remain explicit. This is not a budget-matched method comparison.

16 initial games × 3 focal seats = 48 games/model, 192 for four models. Eight ID and eight dependency-geometry OOD, each split balanced across binary/linear and 2/4 rounds. Three players, two commitments/player, three goals, six/twelve proposal opportunities. Matched ID/OOD pairs retain the proposal schedule, size, scoring mode and public background profile (balanced/avoid-heavy). Each scenario and realized preference world is fixed across model arms and seat rotations. Sampling stays at the existing evaluation settings: temperature=1, top_p=1, max_tokens=1024, one retry, one rollout per seat. More rollout seeds are not independent structures.

ID means training geometry with a fresh indexed preference world, not an independent structural test. Its eight rows span only three distinct geometries. OOD spans eight distinct geometries absent from both BP and self-play train/validation in `data_binary_linear_v3`. Canonicalization quotients player, commitment and goal permutations and ignores scoring/timing/priors. This exclusion does not claim absence from arbitrary older unused files or all development history. No model results or utility properties were used in admission. Native random generation enforces connectedness; preference sampling follows the public weighted prior and native rejection constraints.

Training rules, observation renderer, tool schema, native invalid-action retry and rewards are reused unchanged. Only the acting focal seat routes to M; the two other seats always route to Q0. Each player receives only its visible history, own preferences and private query answers. Complete raw HTTP requests/responses and observed actions are saved for every game.

Main outcome: focal terminal utility, with team utility, completion rate, invalid-call and truncation rates. ID/OOD and binary/linear are separated. A model protocol failure has missing terminal utility, not zero. Conditional terminal averages are accompanied by completion rate and conservative full-cohort utility bounds. Infrastructure failures are separate, stop subsequent batches and invalidate cohort interpretation. Seats/worlds sharing a geometry are dependent; no naive per-seat confidence intervals are reported. Compare the same scenario-seat keys across models, including pairs where only one completes. `EXIT_CODE=0` means all jobs recorded without infrastructure exceptions, not all episodes completed.

## Teacher condition

Not included in this release. The previous design requires a same-visible-information selected-policy teacher, never `PerfectInfoSolver`, which sees hidden preferences. Existing exact private teachers enumerate the entire remaining public tree and world-indexed information sets; feasibility at these full-game sizes and the treatment of off-policy LLM evidence remain unvalidated. A teacher timeout must not silently change this suite's geometry or turn a heuristic into an exact oracle. The fixed-Q0 comparison can proceed independently. The teacher condition remains outstanding rather than being claimed complete.

## SoC

Use an independent extracted runtime and existing `/home/e/e1300530/tmp/marshal-vllm09` (vLLM 0.28.0). No dependency installations. Two allocated GPUs, focal on one and Q0 on the other, native Hermes tool parsing. Both H100-96 and H200-141 profiles request TWO GPUs for this comparison (unlike the one-GPU homogeneous CalBench path).

Default Q0: `/home/e/e1300530/models/Qwen3-4B-Instruct-2507`; override `BENAC_A_Q0` if needed. Checkpoints must be exported Hugging Face directories with config/tokenizer/weights, not raw Megatron directories.

```bash
bash examples/final_evaluation/submit_benac_a_soc.sh h100-96 q0 q0 smoke
```

This uses a development validation reset, all three seats, NOT the frozen 16 test resets. Inspect `runs/benac_a_soc/q0-smoke.latest`, its `EXIT_CODE`, `games/summary.json`, `games/*/calls.jsonl` and server logs. Model format failures are diagnostic outcomes; missing tool parser or endpoint failures must be resolved before formal runs.

Then submit the fixed four conditions, selecting explicit exported paths:

```bash
bash examples/final_evaluation/submit_benac_a_soc.sh h100-96 q0 q0 formal
bash examples/final_evaluation/submit_benac_a_soc.sh h100-96 /absolute/export/selfplay-step69 selfplay-step69 formal
bash examples/final_evaluation/submit_benac_a_soc.sh h100-96 /absolute/export/bp-step139 bp-step139 formal
bash examples/final_evaluation/submit_benac_a_soc.sh h100-96 /absolute/export/mixed-step59 mixed-step59 formal
```

These are path placeholders; use the existing CalBench model export directories. No checkpoint resampling based on A scores. Each run records model file hashes, inference versions, exact server command and suite manifest. Compare source hashes against the actual training release when interpreting ID/OOD; this freeze uses the local final binary/linear v3 release.

## Local validation

`python -m examples.final_evaluation.benac_a_suite` verifies source/data hashes and 48 native scripted terminal episodes. `python -m pytest tests/agentic/test_benac_a.py -q` checks splits, routing, information isolation, protocol failure and infrastructure semantics. This is CPU validation; SoC inference has not yet been executed.
