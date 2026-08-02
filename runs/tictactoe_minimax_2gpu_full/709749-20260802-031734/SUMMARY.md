# Tic-Tac-Toe minimax self-play experiment

## Run

- Slurm job: `709749`
- Status: completed successfully (`0:0`)
- Runtime: `05:04:01`
- Training steps: 200 (`0` through `199`)
- Hardware: 2 x H100-96GB on one node (`xgpi10`)
- Model: Qwen3-4B-Instruct-2507
- Evaluation interval: 20 steps
- Checkpoint storage: disabled

## Generation and reward configuration

- `max_new_tokens: 600`
- `temperature: 0.7`
- `top_p: 0.8`
- `top_k: 20`
- Stop string: `</answer>`, retained in output
- Prompt requests concise strategy followed by exactly one structured action.
- Training allows one fresh retry after an invalid decision; evaluation uses no retries.
- Optimal-response conciseness bonus: `beta = 0.1`, budget 600 tokens.
- Invalid-attempt penalty: `eta = 0.1`.

## Evaluation results

Evaluation ran before training updates at steps 0, 20, ..., 180. There is no post-step-199 evaluation because checkpoints and a final evaluation stage were disabled.

| Metric | Step 0 | Step 180 |
|---|---:|---:|
| Valid actions | 85.4% | 100% |
| Closed answers | 85.4% | 100% |
| Cap hits / truncations | 14.6% | 0% |
| Median response length | 53.5 tokens | 36 tokens |
| p95 response length | 600 tokens | 69 tokens |
| p99 response length | 600 tokens | 81 tokens |
| Minimax-optimal among valid actions | 68.6% | 68.1% |
| Minimax-optimal across all attempts | 58.5% | 68.1% |

At step 180, X optimality was 71.7% (38/53), O optimality was 63.4% (26/41), and both roles had 100% valid actions. Each role selected actions at seven distinct board positions.

## Interpretation

Training substantially improved formatting reliability and conciseness. It did not produce a measurable improvement in minimax optimality conditional on an already-valid action. The net optimal-output rate rose because invalid and truncated generations disappeared, not because valid move selection became strategically stronger overall.

## Included artifacts

- `eval/step-*.jsonl`: evaluation trajectories and per-decision minimax records.
- `tensorboard/`: TensorBoard scalar event files.
- `logs/custom_logs.log`: consolidated runtime and metric log.

Debug pickle batches, checkpoints, redundant worker logs, Ray internals, and Slurm console output are intentionally excluded.
