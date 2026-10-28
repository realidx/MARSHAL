# 24-parent structure-coverage pilot: remote remaining18

Frozen method `three-player-structure-coverage-pilot-v1`; pool SHA-256 `b47f0568febbfc49aac7cf2e6977997338f95eb7376b990a452faa92ee589ba3`. This is a research pilot; production remains v8 and no model D or training has been performed.

## Results

| Run | Scope | Native terminal certified and Q/S measured | Saved reference independently reloaded |
|---|---:|---:|---:|
| Prior local pilot | indices 0–5 | 5/6 | 5/5 |
| Remote job 1032547 | indices 6–23 | 17/18 | 17/17 |
| Index11 resource retry, job 1032578 | index11 only | 0/1 | 0; no reference existed |
| Combined | frozen24 parents | 22/24 | 22/22 |

Indices 4 and 11 remain unavailable and unmeasured. Index11 timed out in search at the initial120-second candidate budget; its independent retry used600 seconds and again ended with `SearchLimit: Shared teacher wall budget exceeded` after about247 seconds. The failed result is retained; do not assign S=0 or replace the game. The earlier index4 result and retry remain in the prior local pilot artifacts.

Across the22 measured parents,11 have at least one positive private-answer own-S context, comprising87 positive contexts;85 also have positive current-action regret. These are context counts, not independent games. Remote18 alone has8 positive parents and81 positive contexts; one prior six-case pilot contributes3 parents and6 contexts. Different masks produce different reference policies, and the two missing games prevent a complete12-pair comparison; these counts alone do not demonstrate the new distribution solves signal sparsity. Historical-answer S and response social-tie information are separate from private-answer own-S.

## Archive

After checking out `game-slice`:

```bash
python3 new/structure_pool_remote_results_20261029/verify.py
mkdir -p /tmp/structure-pool-remote-results
tar -xzf new/structure_pool_remote_results_20261029/results.tar.gz -C /tmp/structure-pool-remote-results
```

The archive preserves raw files under their original paths relative to `/home/e/e1300530/tmp/structure_pool_remote_20261029/`: frozen input and registration snapshot; the remote18 run, 17-reference independent reload, index11 retry and its empty reload; per-case full recorded source snapshots, configs, original worker logs, terminal certificates/reference NPZ, compressed Q/S labels, examples, complete results, scheduler and resource evidence; doctor, tests and pinned Conda package builds.

Also retained as **quarantined evidence**: job1032520 failed before starting because of Slurm CPU environment mismatch; job1032528 was cancelled after it used Python3.13/NumPy2.5/SciPy1.18 instead of the pinned environment; job1032536 failed before starting because `/usr/bin/python3.12` was unavailable on the compute node. The wrong-environment run `remote_remaining18_20261029` must not be used as final results. Successful job1032547 and retry1032578 used the isolated Python3.12.16/NumPy1.26.4/SciPy1.12.0 Conda environment, with one numerical thread per worker.

`MANIFEST.json` records every original file's SHA-256 and archive hash. `verify.py` validates every archive member without extraction. `SUMMARY.json` keeps run outcomes separately. `SCHEDULER_ACCOUNTING.txt` records completed and failed jobs. Virtual-environment binaries and Python bytecode are excluded; exact Conda package builds are in `preflight_runtime_v4/conda-explicit.txt`.

The complete solver, game and label method were unchanged; this run's Linux resource limits,18-worker concurrency and software environment are documented in the newly registered execution snapshots. Resolved runtime `pipeline_snapshot.json` files record actual argv, source identities and configuration. The original closed pilot snapshot remains unchanged.
