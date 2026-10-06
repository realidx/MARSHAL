# Terminal D v4: Qwen3-4B-Instruct-2507 delta evaluation

Slurm job 915300 completed with exit code 0 on xgpi13 (one H100-47, gpu
partition) in 11m04s. This is the requested v4 delta run, not a rerun of the
previous 800-question panel: 16 parents, 78 selected candidates, 624
trajectories; 75 train candidates, no validation candidates, three test candidates.

## Protocol

Package: examples/strategic_slices/strategic-slices-terminal-D-v4-refill32.tar.gz
at game-slice commit 0bffe95. Archive SHA256:
2fe218a8359ac1c75c3cf27feb492555c4957f34c7884427b7aac2da16e82876.
All 522 bundled file hashes were verified before execution.
Dataset manifest SHA256:
a4330e5b5038d2e33e11ebd366651f2ed388cb850b1fa7ef6e4539d9d0bb06e9.

The run used the package's terminal_d_soc_v4_delta.json: 32 workers,
completion-driven refill, eight independent reset/model/reference draws per
candidate, seed 42, temperature .8, top-p 1, top-k -1, repetition penalty 1,
4096 output tokens, 16384 context, BF16 TP1, Hermes act parser, GPU memory
fraction .4. This was a fresh run; no previous measurement results were imported.

## Results

- 731 model calls: 702 valid legal actions (96.033%), 28 truncated (3.830%),
  one invalid action/format (0.137%).
- 595/624 terminal trajectories (95.353%); 28 truncation failures (4.487%)
  and one invalid-action failure (0.160%). Failed utilities remain null.
- All eight trajectories completed for 56/78 slices: 53/75 train and 3/3 test.
- Mean D among complete train slices: 0.405432; among the three complete
  test slices: 0.666667. D is V_star minus mean native terminal utility.
- Train: 31 slices have observed root-value contrast, 22 of them are complete;
  20 have mixed optimal/suboptimal first actions within identical visible
  prompts, and 27 have sampled terminal reward contrast.
- No model training or final 100-slice selection was performed. The diagnostic
  threshold of 100 complete training slices with root-value contrast is unmet.

This delta subset differs from the previous full panel. Its higher truncation
rate or different mean D cannot establish a change in model ability. Eight
replicas yield coarse descriptive uncertainty. Reward contrast includes hidden
world/reference randomness and is not a GRPO active-group rate.

## Full evidence

summary.json, REPORT.md, slices.jsonl, train_signal_candidates.jsonl and
protocol.json are directly readable. terminal-d-v4-full-results.tar.gz contains
the complete run: all parent trajectories, requests/responses, transport and
server logs, runtime records, source snapshots and completion markers. No
model weights are included. ARCHIVE_MANIFEST.json records archive and per-file
SHA256 hashes. slurm-915300.out preserves job stdout. Runtime absolute paths
are provenance records rather than portable command paths.

The final COMPLETE.json hashes and every archived file were independently
verified before this publication. Extract the archive into a new directory to
inspect the raw evidence; use ARCHIVE_MANIFEST.json to verify its files.
