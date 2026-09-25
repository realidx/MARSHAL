# Micro24 continuation and CalBench evidence (2026-09-25)

This archives the micro24 continuation from native checkpoint-39 of training job 878930 through updates 40–79 in job 879089. The continuation finished with exit code 0 and produced complete native checkpoint-79. The original response-token budget and token-based learning-rate schedule were retained; the fixed 40-update exposure plan was repeated with new request seeds. No native weights, HF weights, optimizer files, or regenerable Triton caches are in Git.

| Frozen 24-case CalBench | Job | Coordination success | Successful and optimal | Healthy transport | Untruncated | Strict envelope failures |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| checkpoint-49 | 879142 | 6/24 | 5/24 | 24/24 | 19/24 | 14 |
| checkpoint-79 | 879266 | 4/24 | 3/24 | 24/24 | 20/24 | 9 |

The same frozen profile was used for both: H100-47, `VLLM_BATCH_INVARIANT=1`, TP=1, `max_num_seqs=32`, `parallel_games=8`, temperature 0, 4096 output tokens, prefix caching on, chunked prefill and cascade attention off. Each run completed 24/24 with exit code 0. In the per-family results, replan coordination fell from 3/6 to 0/6 while loose rose from 3/6 to 4/6; blocked and dense remained at 0/6. Truncation and format errors must be considered when interpreting individual failures.

Archives:

- `training_micro24_steps40_79.tar.gz`: raw training logs, resolved configuration, per-step metrics, calls, validation, monitoring, and retention records; checkpoint weights are excluded.
- `calbench_step49.tar.gz`, `calbench_step79.tar.gz`: full run directories including per-game results, traces, events, transport and server logs; Triton caches are excluded.
- `checkpoint_export_metadata.tar.gz`: checkpoint-79 completion manifest and verified HF export provenance, without model weights.
- `job_logs_and_launchers.tar.gz`: Slurm, export and CalBench logs and the launcher scripts used.
- `source_snapshot.tar.gz`: the three continuation-modified source files. The synthetic standalone source commit was `4a2c389ba98532f353aca6deace61ddd7b949039`; it is **not** an `origin/new` commit. Its parent `f251e654e3a5aa01cd927cd5a01a2cdee6e882e5` snapshots the previously verified training source. Use the source archive and run configuration for exact provenance.

Archive SHA256:

```text
d4df152ad0db6f115d323469d5e615726f2c846120282d75b44467861468aa27  calbench_step49.tar.gz
1044f8f54d919e169589b0bb36fdc253f4a9188c997c23b2b0ba34691fa6fe1c  calbench_step79.tar.gz
2063708623c918c42d55a926ee50209d1fcc0f14f74c43e3b66d011b54097432  checkpoint_export_metadata.tar.gz
6afc6de95aa3b407671be1e6ee591b52f5863088eba86c3d7b6afbc33c9bf63f  job_logs_and_launchers.tar.gz
5988b4dd349600721439741ecbbde106522687b359acd24b4cd6c593e5cc5f78  source_snapshot.tar.gz
3a90267161c9c0a5cfb7eb42f19134ab766c56b6218ac5833721c926e45bfa1d  training_micro24_steps40_79.tar.gz
```
