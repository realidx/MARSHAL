# O / SP / C training and CalBench evidence (2026-09-22)

This bundle preserves the available O, SP and C training attempts through O step 99, SP step 19 and C step 89, plus their seven completed CalBench evaluations. It is raw evidence for subsequent analysis, not a claim that a later checkpoint is better.

## Contents

- `training/outcome.tar.gz.part-*`: O training attempts, including the initial run `871285` and continuation `871623`.
- `training/selfplay.tar.gz.part-*`: SP attempts and the completed run `871285`.
- `training/conditioned.tar.gz.part-*`: C initial run `871298` and continuation `871607`.
- `calbench/*.tar.gz`: O steps 19/29/39/99, SP step 19, and C steps 43/89. These include per-game results, traces, transport logs, server logs and execution identities.

Training archives retain available `train.log`, `metrics.jsonl`, `calls/`, `units/`, `validation/`, `static_o_monitor/`, configuration, environment, probability warnings, phase records and exit markers. The archives include failed early attempts to preserve provenance. Model checkpoints, actor-training weight directories, empty per-step `games/` placeholders and generated Triton caches are intentionally excluded. No model weights or HF exports are included.

The training archives were made from `/home/e/e1300530/tmp/MARSHAL-benac-results-push/runs/social_mixed/`; CalBench archives were made from `/home/e/e1300530/tmp/MARSHAL-calbench-stream-20260920/runs/calbench_soc/`. The source checkout was `d5d3987` with a clean worktree before this bundle. `origin/new` was `3041d74` when packaging began.

From the `training/` directory, reconstruct and verify the archives:

```sh
cat outcome.tar.gz.part-* > outcome.tar.gz
cat selfplay.tar.gz.part-* > selfplay.tar.gz
cat conditioned.tar.gz.part-* > conditioned.tar.gz
sha256sum -c ARCHIVES.sha256
tar -tzf outcome.tar.gz
```

Run the CalBench checksum command from `calbench/`: `sha256sum -c ARCHIVES.sha256`.

The checkpoint step labels are not equal training-token budgets. In particular C step 89 is a paused continuation rather than a completed full-budget run. Compare cumulative generated response tokens and per-case outcomes, not just step numbers or the highest validation point.
