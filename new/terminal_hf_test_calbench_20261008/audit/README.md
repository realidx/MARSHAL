# Terminal test audit, 2026-10-08

The reported near tie is not evidence that both checkpoints behave identically. Paired full-window success differs on 284/1600 trajectories: best-only 146, latest-only 138, both-success 873, both-failure 443. The aggregate difference is 0.5 percentage points. A paired bootstrap resampling the 25 parents (10,000 draws, seed 42) gives best-minus-latest 95% CI [-6.8125, 8.0625] percentage points.

## Coverage and interpretation

- Test: 200 slices from 25 parents and 19 structural families, each with 8 hidden-world/reference-policy replicas. Temperature 0 does not produce 8 independent model samples. There are only 200 distinct root prompts; every replica has the same root prompt for its slice.
- Test and validation each have zero `information_positive` and zero `detectable_information_value` entrances. The training candidate pool contains 12 positive-information slices, protected in the selected training set. These fields describe information value at the entrance, not every subsequent decision. The current held-out test cannot establish independent generalization on strong information acquisition.
- 50/200 slices have flat root Q; all belong to k=2 or k=3. Every test slice has positive whole-window C_span. Thus these are not entirely signal-free tasks. Among non-flat evaluated steps, accuracy is best 67.7472%, latest 67.4054%, versus aggregate approximately 74.65%.
- k is a maximum number of controlled decisions, not a guarantee of that many decisions before native termination.

| Declared k | Slices | Best whole-window success | Latest whole-window success |
|---|---:|---:|---:|
| 1 | 97 | 67.0103% | 63.9175% |
| 2 | 71 | 57.5704% | 64.4366% |
| 3 | 32 | 67.1875% | 58.2031% |

## Integrity checks

- No overlap of training/test parents or exact raw games.
- All paired slice IDs, replica IDs, member/world indices and seeds match.
- Actual terminal inference requests use temperature 0 and max_tokens 1024. Export rotary base is 5,000,000.
- Recomputed the 200 saved root Q tables from frozen reference trees: maximum absolute delta 1.3322676295501878e-15, no mismatches. See `root_q.json`. This recomputation uses the production solver and is a consistency check, not an independently implemented oracle.
- Recomputed every recorded binary reward from validity and saved action Q using the production epsilon 1e-7: no mismatches.
- Original Validator response replay results are recorded in `replay.json`. Compare score/game equality separately from any floating-point oracle-detail differences in call logs.

No test data, generation settings or historical result scores were modified by this audit. CalBench is a separate 24-case evaluation and should not be pooled with terminal slice accuracy. This terminal test has historical base-model exposure and is not a blind final benchmark.

## Completed original-Validator replay

Best: 4,349 exact requests; latest: 4,418 exact requests. For both exports, all slice score summaries, slice games, generated token counts, full-game metrics, full-game records and full-game calls exactly match. Slice call details differ only in Q/gap floating-point values: best 57 calls, latest 60 calls, maximum absolute difference 4.440892098500626e-16. All rewards and optimal action sets match. See `replay.json` and `replay_numerical_differences.json`.
