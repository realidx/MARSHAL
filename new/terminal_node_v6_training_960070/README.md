# Terminal node v6 training — Slurm job 960070

Cancelled by the user on 2026-10-17 after 15:49:44 of allocation time. This is an interrupted run, not a completed 6M-response-token experiment.

- Model: Qwen3-4B-Instruct-2507, trained from base on one H100-96, node xgpi10.
- Started: 2026-10-16 22:56:47 Asia/Singapore. Allocation limit: 24 hours.
- Completed updates: 307 (metric steps 0–306); recorded training response tokens: 1,123,499.
- Calls, games and units contain 308 collections. The final collection (step 307) has no completed update metric; do not count it as an optimizer update.
- Best retained checkpoint: checkpoint-269, after 270 updates / 1,001,172 response tokens. Checkpoint metadata is included; model/optimizer tensors and serialized RNG/scheduler states remain local.
- Last evaluated validation full-window success: 0.8333333333; baseline: 0.5104166667. Validation has no positive-information root decisions.

## Download and extract

After checking out `game-slice`, run from the repository root:

```bash
python3 new/terminal_node_v6_training_960070/verify_logs.py
mkdir -p /tmp/terminal-training-960070
cat new/terminal_node_v6_training_960070/raw/training-960070.tar.gz.part* > /tmp/training-960070.tar.gz
tar -xzf /tmp/training-960070.tar.gz -C /tmp/terminal-training-960070
```

The archive contains original bytes under `run/`: all per-step calls (prompts, responses, token IDs and behavior log-probabilities), games, units, validation trajectories/results, metrics, phase timings, probability warnings, worker logs, resolved configuration, environment, source manifest, model hashes, checkpoint retention records and checkpoint metadata. `scheduler/` contains the original Slurm output file and the final accounting snapshot. The original Slurm output file is empty; worker logs and structured phase/metric files contain runtime evidence.

`raw/MANIFEST.json` lists every archived file's original path, size and SHA-256; it also lists excluded checkpoint tensor/state files and archive-part checksums. Archives are lossless gzip, split into 32 MiB parts. `verify_logs.py` verifies every part, the concatenated archive, and every original file without extracting it. `package_logs.py` records the packaging procedure and original source directory.

## Timing interpretation

Completed phase totals include approximately 9.06 hours rollout, 2.95 hours optimizer update, 2.55 hours weight synchronization, 0.99 hours reference log-probabilities, 0.12 hours validation and 0.06 hours checkpointing. The cumulative `reference_restore_seconds_total` (7.41 hours at the last metric) is **inside rollout**, not an additional phase: it measures reconstruction/loading/verification of frozen reference game trees, not reference-model loading. `generation_seconds` measures time inside stream polling and is not a complete GPU-generation profile. Response-token totals exclude prompt tokens.

Existing frozen training data/reference archives are documented in `new/terminal_hf_test_calbench_20261008/README.md`; this bundle preserves the exact source and configuration manifests for this run.
