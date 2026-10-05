# Terminal slice D and signal diagnostic

800 slices; 6400 trajectories; 6213 completed.

| Split | Slices | Complete slices | Reward contrast | Root value contrast | Mixed optimal/suboptimal root |
| --- | --- | --- | --- | --- | --- |
| train | 504 | 413 | 179 | 100 | 60 |
| validation | 96 | 80 | 38 | 21 | 19 |
| test | 200 | 164 | 82 | 63 | 42 |

Reward variation includes environment noise. Root-Q contrast uses identical visible prompts, optimal continuation within remaining window, and is not full-trajectory success or proof of learnability.

No training or final 100-slice selection. Per-slice D, uncertainty, failures and signal diagnostics are in `slices.jsonl`.
