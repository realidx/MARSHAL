# Frozen100-parent CPU oracle results —2026-10-22

Current union: **85/100 certified parents;15 unavailable**. This is a union of independently certified references from multiple research solver versions, not one homogeneous solver run. Failed parents remain missing labels; no parent was replaced, no tolerance relaxed, and no Q/S/D measurement or model training was performed.

| Run | Slurm job | Scope | Certified | Unavailable |
|---|---|---:|---:|---:|
| Resource probe |986645|8|5|3|
| Base |986646|100|65|35|
| Extended, preserving base |986695|100|74|26|
| Isolated repair v3 |988647|26|10 new|16|
| v4 backward repair, index34 |989122_0|1|0|1|
| v4 bounded sparse solver, index6 |989122_1|1|0|1|
| v4 staged working set, index24 |989122_2|1|1 new|0|
| v4 staged extension, remaining15 |989412|15|0|15|

The85-reference union is74 extended results (including65 imported base references),10 v3 repair results, and1 v4 staged result. `CERTIFIED_REFERENCES.json` identifies the exact NPZ, result record, hashes and original source-bundle identity for every accepted parent. `SUMMARY.json` lists all runs and remaining indices.

Remaining indices (zero-based frozen `index`): **6,8,9,25,29,31,34,46,50,51,58,73,74,90,95**.

## Download, verify and extract

From the repository root after pulling `game-slice`:

```bash
python3 new/remote_solver_results_20261022/verify_results.py
mkdir -p /tmp/oracle-results-20261022
tar -xzf new/remote_solver_results_20261022/raw/all-oracle-runs.tar.gz -C /tmp/oracle-results-20261022
```

Archive paths correspond to the original `oracle_cpu_20261021/` directory. They include all three standalone source bundles and their manifests, original100-parent input, protocols, all run snapshots, attempts, failures, independently certified NPZ references, certificates/native audits, numerical optimizer events, diagnostic candidate NPZs, resource samples, preflight doctor/tests/package versions, and top-level Slurm stdout. Virtualenv binaries/packages and generated Python bytecode are excluded. Package versions are preserved; no model/GPU environment is required.

**Diagnostic `best_candidate.npz` files are unaccepted search candidates, not certified references.** Use only entries in `CERTIFIED_REFERENCES.json` for the85 accepted references. They retain their original identities; they have not been repackaged into a new training dataset.

`raw/MANIFEST.json` lists the size and SHA-256 of every original file and the archive. `verify_results.py` verifies every byte without extraction, then checks85 reference provenance entries. `package_results.py` records packaging and integrity checks. `SCHEDULER_ACCOUNTING.txt` preserves final job accounting.

## Certification and interpretation

During each successful solve, the candidate passed full native terminal independent deviation, local support, response-only social tie and native-transition checks under that source version. Final post-run audits were **hash-only**; no additional full reload/re-certification of the85-reference union has been performed. The original full acceptance functions were preserved in research v3/v4; changed search algorithms generate candidates and do not establish acceptance on their own.

Version records are registered in `examples/strategic_slices/versions/index.json`. Initial snapshots intentionally record their submission-time state; use this report and original `COMPLETE.json`/`summary.json`/scheduler records for final outcomes. Source snapshots, diagnostic summaries, launch scripts and tests also remain in `new/remote_solver_slurm_20261021/`, `new/remote_solver_repair_v3_20261021/`, `new/remote_solver_experiments_v4_20261021/` and `new/remote_solver_staged15_20261021/`.

Some compute-node ISO wall-clock timestamps differ from scheduler timestamps; original bytes are retained. Compare solver durations measured by monotonic clocks and Slurm accounting for elapsed-time analysis.
