# Old B/P complete training calls

This archive preserves the complete surviving per-update raw training calls for the old B/P chain. The two jobs are kept separate because job 861241 resumed from checkpoint 99, while job 860494 had already produced unsaved updates 100–102. Those overlapping step numbers represent different trajectories.

| Archive | Source job | Recorded steps | Files | Original calls directory |
|---|---:|---:|---:|---|
| `860494-steps-0-102.tar.gz` | 860494 | 0–102 | 103 | `/home/e/e1300530/tmp/MARSHAL-train-new-20260918-0f6d73a/runs/social_mixed/bp-seed42-860494/calls` |
| `861241-steps-100-205.tar.gz` | 861241 | 100–205 | 106 | `/home/e/e1300530/tmp/MARSHAL-bp99-sp-stage-20260919/runs/social_mixed/bp-seed42-861241/calls` |

Each archive contains the original `calls/step-N.jsonl` files without field changes. All expected files were checked to be present and nonempty before packaging. SHA256 hashes of the compressed archives are in `SHA256SUMS`.

The run configurations, full per-step metrics, validation results, and previously selected 5-step call windows are in [`../training_chain_evidence_20260921/`](../training_chain_evidence_20260921/). Use the job ID to join calls to those records; do not merge the overlapping steps by step number alone.
