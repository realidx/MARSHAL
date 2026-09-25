# Micro13 / micro24 training and CalBench evidence (2026-09-25)

This directory archives the raw micro-learning runs and every associated CalBench attempt. Native checkpoints, HF weights, and regenerable Triton compilation caches are **not** included.

| Arm | Training starts / resume | CalBench step 9 | Step 19 | Step 39 |
| --- | --- | --- | --- | --- |
| micro13 | 878813 / 878930 | 6/24 success, 3/24 optimal, mean headline 0.540 | 4/24, 4/24, 0.497 | 4/24, 1/24, 0.474 |
| micro24 | 878813 / 878930 | 2/24 success, 2/24 optimal, mean headline 0.495 | 4/24, 1/24, 0.508 | 9/24, 6/24, 0.630 |

The table uses only complete 24/24 reruns (step 9 jobs 878924/878925; step 19 jobs 878966/878967; step 39 jobs 879032/879033). The first step-9 attempts, 878848/878849, ended after 14/24 and 15/24 results respectively; their raw records are retained but must **not** be interpreted as full-panel scores. Initial training job 878806 failed before an update due to the micro collector interface; its logs are included. The 878813 training jobs reached step 19 but were interrupted during checkpoint writing by storage quota. Both arms resumed from complete checkpoint-9 in job 878930 and finished checkpoint-39 with exit code 0.

Archives:

- `training_micro13.tar.gz`, `training_micro24.tar.gz`: complete run logs for 878806, 878813, and 878930, including resolved configs, manifests, per-step metrics, full calls, validation, probability warnings, worker logs, and checkpoint completion/retention metadata. Weight and optimizer directories are excluded.
- `calbench_micro13.tar.gz`, `calbench_micro24.tar.gz`: four raw CalBench run directories per arm (interrupted step-9 attempt plus the three complete runs), including per-game result, trace, events, transport, execution identity, and server log. Only Triton compilation caches are excluded.
- `job_logs_and_launchers.tar.gz`: Slurm/export/CalBench stdout and stderr and the launcher scripts used during this work.
- `training_source_snapshot.tar.gz`: exact local micro collector, training entrypoint, test, and shell entrypoints used for these runs.

The original training source recorded commit `0a4923ef907f2761b456c5c5e31e2c35d46c19ee`; after its shared Git worktree metadata disappeared, the unchanged working source was snapshotted into a standalone clean local commit `f251e654e3a5aa01cd927cd5a01a2cdee6e882e5` for resume. These local commit IDs are provenance markers, **not** commits on `origin/new`; use the source snapshot for exact executed files. The frozen CalBench profile used `VLLM_BATCH_INVARIANT=1`, TP=1, `max_num_seqs=32`, `parallel_games=8`, temperature 0, and 4096 output tokens.

Both arms used the `data_reasoning_v6` manifest SHA256 `730f0d819b3a9e48cbcdc781b17cd5db580317d569f196ae0b97f2fb66e0729d`. Micro-bank identities: micro13 `55ab610221f137c246e931a6645e8180fc21d8beb27c762d7bffe9420b42675d`; micro24 `9bbe608aeb76f8d0109d16ece5ea3bffdb0b9a478e22714544d6b08490fa2d7f`.

Archive SHA256:

```text
f50e7733b28ff85654e67677bd3c83ba9e1666d3854c7089ba47a0388edca541  calbench_micro13.tar.gz
a35da7c6f193e16bc9b9df6e8f7ed291d49e7256b6ced307e2262cc2578bea76  calbench_micro24.tar.gz
95e858254dcbd25cd37432429b1ce104c56a781d9363d18db015a2013ee35ca8  job_logs_and_launchers.tar.gz
e9a674bebbdda765d14159bcfb0a7cf87e4e02a1a5edc1f7c491d72c00d88a11  training_micro13.tar.gz
c97cf19285cd86d764861ca74486c103281c4ac7f48469b37e34acb8bc5334a6  training_micro24.tar.gz
aca29c1ffc3f8ae570c362c5d2bab555ced258ce2527ef4f60cb64ea57357170  training_source_snapshot.tar.gz
```
