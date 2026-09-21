# Old BP, new BP, and new SP training-chain evidence

This directory is a lossless evidence bundle for the three training chains discussed on 2026-09-21. It preserves run-time manifests rather than reconstructing settings from the current checkout.

## Scope and chain boundaries

| Chain | Run segment | Recorded update range | Source commit | Dataset manifest SHA256 |
|---|---:|---:|---|---|
| old BP | 860494 | 0--102 | `1a69148339f154ee35b505606c01321addc34498` | `9e5aa61fc089189a062d4aa296df74a635d50be0e49c7478a7450358c7d2fa7d` |
| old BP resume | 861241 | 100--205 | `c4c74ac1a652590f62491c1df937f9baec0bba2a` | `9e5aa61fc089189a062d4aa296df74a635d50be0e49c7478a7450358c7d2fa7d` |
| new BP initial | 865319 | 0--29 | `dbd4585ea6a4acf01d3acc0ad893ed0c98a1c52f` | `730f0d819b3a9e48cbcdc781b17cd5db580317d569f196ae0b97f2fb66e0729d` |
| new BP resume | 866677 | 30--99 | `dbd4585ea6a4acf01d3acc0ad893ed0c98a1c52f` | `730f0d819b3a9e48cbcdc781b17cd5db580317d569f196ae0b97f2fb66e0729d` |
| new BP resume | 868798 | 100--149 | `dbd4585ea6a4acf01d3acc0ad893ed0c98a1c52f` | `730f0d819b3a9e48cbcdc781b17cd5db580317d569f196ae0b97f2fb66e0729d` |
| new SP initial | 865319 | 0--9 | `dbd4585ea6a4acf01d3acc0ad893ed0c98a1c52f` | `730f0d819b3a9e48cbcdc781b17cd5db580317d569f196ae0b97f2fb66e0729d` |
| new SP resume | 866677 | 10--41 | `dbd4585ea6a4acf01d3acc0ad893ed0c98a1c52f` | `730f0d819b3a9e48cbcdc781b17cd5db580317d569f196ae0b97f2fb66e0729d` |

The `865319` BP and SP run directories had already been deleted for storage recovery before this archive was requested. Their exact raw step 0--29 and 0--9 artifacts therefore cannot be recovered from the filesystem. They are listed to make the chain boundary explicit, but are not silently reconstructed. In particular, this bundle does **not** pretend that a validation from another run is the missing new-run step 0.

Old BP has an overlap at steps 100--102 because the resume began from checkpoint 99 while the original job had already generated later, unsaved updates. Treat `861241` as the authoritative resumed branch after checkpoint 99; the two overlapping trajectories are not the same continuation.

## Contents

- `*/segments/<job>/`: exact `experiment.json`, resolved ROLL configuration, environment/version records, topology/NCCL evidence, retention log when present, and the complete training log.
- `*/metrics/<job>.jsonl`: every surviving per-update metric row, unfiltered. `*-phases.jsonl` contains the matching phase/timing stream. Resume segments are separate so duplicated update numbers remain unambiguous.
- `*/validation/*.json.gz`: every surviving full per-question validation snapshot, including prompts, generated calls, rewards, protocol records, and aggregate metrics. Old BP includes its actual `step-0.json`. The deleted new-run initial segments mean their actual step-0 snapshots are unavailable.
- `*/calls/*.jsonl.gz`: raw training calls for three consecutive five-update windows per chain. The selected windows are listed below.
- `data/`: the exact dataset manifests plus SHA256 for every file in the two run-time data directories. Absolute paths intentionally remain in the checksum lists for provenance.
- `source/`: metadata/stat and complete single-commit patch for every recorded source commit.
- `submission/`: surviving scheduler wrappers relevant to these runs. See the provenance warning below.
- `FILES.sha256`: SHA256 of every archived file other than the checksum file itself.

## Selected training-call windows

| Chain | Early | Middle | Late |
|---|---|---|---|
| old BP | 860494 steps 0--4 | 861241 steps 100--104 | 861241 steps 201--205 |
| new BP | 866677 steps 30--34 | 866677 steps 88--92 | 868798 steps 145--149 |
| new SP | 866677 steps 10--14 | 866677 steps 24--28 | 866677 steps 37--41 |

For new BP/SP, “early” means the earliest raw calls still present after deletion of job 865319, not the beginning of training.

## Configuration and source-state provenance

Every surviving `experiment.json` records `source_version.kind=git`, the commit shown above, and `clean=true`. Thus the run evidence says there was no uncommitted source diff for these segments. No uncommitted patch is invented or inferred. The full resolved configuration is archived per segment because it is stronger evidence than today’s defaults.

Common recorded settings include Qwen3-4B-Instruct-2507, TP=2, sequence parallelism, BF16, full recomputation, 4096 sequence length, 3072 prompt length, GRPO, one PPO epoch, clipping 0.2, KL coefficient 0.01, no advantage whitening, sequence-mean/token-mean loss aggregation, constant `1e-6` learning rate, rollout temperature 1.0, and H100-47 cross-parent execution. Consult each `resolved_config.json`; do not use this paragraph as a substitute.

The old initial and resume segments used different clean commits (`1a691...` and `c4c74...`). New BP/SP used `dbd458...`. The archived patches show what each commit itself changed relative to its first parent; they are not diffs between entire training recipes.

## Submission-script provenance warning

The exact commands are recoverable in the run manifests/configs and logs. Several external `/tmp` wrappers survived and are archived because they document H100-47 selection and signal forwarding. They did not embed a cryptographic job-to-script identity, so the archive does not claim every copied wrapper can be uniquely assigned to every historical job.

The strongest mappings are:

- `social-bp-sp-h10047-v6-4alloc-wrapper.sh`: new v6 four-MIG BP+SP launch family used for the 866677 continuation, with two cross-parent TP=2 pairs and process-group signal forwarding.
- `social-bp-resume-h10047-3alloc-wrapper.sh` plus `sbatch_train_bp_keep1.sh`: new BP-only resume launch family used for the later continuation represented by 868798.
- The remaining old four-allocation wrappers document the old BP/SP launch families, but their filenames alone are not sufficient proof of a unique job association.

## Reading compressed records

Examples:

```bash
gzip -cd old_bp/validation/860494-step-0.json.gz | jq '.metrics'
gzip -cd new_sp/calls/866677-step-39.jsonl.gz | jq -c '.' | less
sha256sum -c FILES.sha256
```

All gzip members contain the original bytes from the run directories; no JSON fields were dropped or normalized.
