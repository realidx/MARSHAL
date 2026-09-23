# Old B/P-99 diagnostic and CalBench raw evidence

All seven archives are for the old B/P-only checkpoint-99 HF export at
`/home/e/e1300530/tmp/hf-exports-860494/bp-step99`. The model weight
SHA256 recorded by the frozen CalBench run and strengthened diagnostic is
`aab6fdb53542132f3818909f533678b5d01d31ce984e53674ebf90e14b737ab9`.
The archives contain raw calls, per-game/structure results, protocol and
runtime metadata, and server logs; they do **not** contain model weights.

## CalBench

| Archive | Protocol | Result | Interpretation |
| --- | --- | --- | --- |
| `calbench/original12-860852.tar.gz` | Original 12-game formal suite | 8/12 coordinated, 7/12 optimal | Historical result; not the later 24-game stream suite. |
| `calbench/stream24-prefreeze-868599.tar.gz` | 24-game stream before frozen batch-invariant profile | 10/24 coordinated, 45/72 meetings | Historical reference; serving behavior may differ. |
| `calbench/stream24-frozen-868934.tar.gz` | Frozen 24-game stream, batch-invariant v1 | 10/24 coordinated, 44/72 meetings, headline 0.593 | Direct protocol comparison to the frozen D CalBench runs in `new/d_evidence_20260924/`. |

The CalBench archives retain all saved games, raw transport logs, scenario
manifests, run identity and runtime files, server log, and completion marker.
Generated Triton compilation caches are excluded.

## Diagnostic

| Archive | Protocol | Use |
| --- | --- | --- |
| `diagnostic/v5-868939.tar.gz` | v5 | Historical only; v5 controlled P retained behavioral chronology. |
| `diagnostic/v6-870264.tar.gz` | Original v6 | Historical intermediate version. |
| `diagnostic/v6s-870332.tar.gz` | Strengthened v6, first run | Repeat of the same model and protocol. |
| `diagnostic/v6s-874313.tar.gz` | Strengthened v6, later run | Canonical comparison to Q0 and D v6s diagnostics. |

The two strengthened v6 runs used the same model weight hash, manifest SHA256
`94bccbb8b86f5b728b6f594206a7c39adb25ecfb1b90f0b53480cad06df177dc`,
runtime SHA256
`d02d8d3a0b3f55da445afdc711ccffc698b5449f8f8465bf8446a4ea4dc7fb8a`,
temperature 0, three repeats, and batch-invariant serving. The canonical run
returned all 96/96 planned structure replicas. Its paired repair gain must be
read with the valid-row coverage in its own `summary.json`; it is not a
simple difference between condition-specific means.

Extract any archive with `tar -xzf ARCHIVE -C DESTINATION`. Verify all
archives with `sha256sum -c SHA256SUMS`.
