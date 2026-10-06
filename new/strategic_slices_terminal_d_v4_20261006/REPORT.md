# Terminal slice D and signal diagnostic

78 slices; 624 trajectories; 595 completed.

| Split | Slices | Complete slices | Reward contrast | Root value contrast | Mixed optimal/suboptimal root |
| --- | --- | --- | --- | --- | --- |
| train | 75 | 53 | 27 | 31 | 20 |
| validation | 0 | 0 | 0 | 0 | 0 |
| test | 3 | 3 | 0 | 0 | 0 |

Reward variation includes environment noise. Root-Q contrast uses identical visible prompts, optimal continuation within remaining window, and is not full-trajectory success or proof of learnability.

No training or final 100-slice selection. Per-slice D, uncertainty, failures and signal diagnostics are in `slices.jsonl`.
