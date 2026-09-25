# D24v2 and OP16-v2 training and CalBench evidence (2026-09-25)

Both arms started independently from Qwen3-4B-Instruct-2507 with seed 42 and completed 40 updates in joint H100-47 job 879365 (exit code 0 for each). Each retained only its complete native checkpoint-39. D24v2 trains O/P/B (96 answers per update); OP16-v2 omits B (64 answers per update) without replacing those exposures. Shared O/P objective weights and the frozen per-update learning-rate sequence follow the v2 source. These are not equal-token arms: actual training response tokens were 1,587,594 and 1,434,800, respectively.

| Frozen 24-case CalBench | Job | Coordination success | Successful and optimal | Mean headline | Healthy transport | Untruncated | Strict envelope failures |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| D24v2 checkpoint-39 | 880768 | 7/24 | 4/24 | 0.544 | 24/24 | 19/24 | 7 |
| OP16-v2 checkpoint-39 | 880769 | 3/24 | 1/24 | 0.396 | 24/24 | 16/24 | 20 |

Both CalBench runs finished 24/24 with exit code 0. The same frozen profile was used: one H100-47 per model, `VLLM_BATCH_INVARIANT=1`, TP=1, `max_num_seqs=32`, `parallel_games=8`, temperature 0, 4096 output tokens, prefix caching on, chunked prefill and cascade attention off. The performance difference is descriptive; the B branch also changes total training exposure and removes/introduces B-context KL, and output failures differ.

Archives:

- `training_d24v2.tar.gz`, `training_op16v2.tar.gz`: raw run configuration, per-update metrics, all saved calls, validation including step 0, monitoring, worker/Slurm logs, and retention records. Native checkpoint weights are excluded.
- `calbench_d24v2.tar.gz`, `calbench_op16v2.tar.gz`: per-game results, traces, events, transport and server logs; regenerable Triton caches are excluded.
- `checkpoint_export_metadata.tar.gz`: native checkpoint completion manifests and verified HF export provenance, without model weights.
- `jobs_and_launcher.tar.gz`: joint training launcher, export/evaluation launchers, and Slurm stdout/stderr. Export jobs were 880766/880767.

Executed training source was commit `e906bbb7fcc06e1c5c640105248fe1a6a140cba7` (on top of `903a3ea`); the two intervening commits fix single-checkpoint retention, joint-run output isolation, and real tokenizer-length checking. Training config and data identities are recorded in each run's `experiment.json` and `resolved_config.json`. Model weights are not in Git.

Archive SHA256:

```text
ce6e2c268b0a072e52d3a04e2d531209a412bef12ce308fd5a48d31b4489482d  calbench_d24v2.tar.gz
3d0aca9c5c391269ab6e2a49c26745f45d8523ef4d5b9a24e83a1d321865a2c1  calbench_op16v2.tar.gz
8ba83f51c5b9645c1715548c3a57ccf6aabd1dc2fb8409afe06026f0c7142da8  checkpoint_export_metadata.tar.gz
0957f0d8a06abfe29bfb0056310d1da9e1f793c313a1b0a13e418a2cf7950b0c  jobs_and_launcher.tar.gz
54de1eca682144b7d88bd842b871de98d2451951fb5f626f098b544a80035a4a  training_d24v2.tar.gz
2081e28f13c6401cd8c003a2eeadf9de7f30ceae4cc53b5c8fcd4f9f4a0d206d  training_op16v2.tar.gz
```
