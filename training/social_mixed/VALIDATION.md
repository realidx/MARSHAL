# Lightweight training validation v2

All training arms evaluate the same fixed development panel at the existing
`eval_steps` interval and at the final update. There is no extra model load:
all eight self-play games use the current actor for every seat.

- B/P: 32 tasks, 16 B and 16 P, one sample each. Deterministic selection covers
  binary/linear kernels, full/reduced belief support, and investigation positive
  and negative cases. Same-mode contrast groups remain intact. Selection depends
  only on development metadata and labels, never model performance.
- SP: eight fixed development resets, one rollout each. Deterministic selection
  covers available player counts, horizons, completion modes and backgrounds.
- Generation settings remain those of the training inference worker. Validation
  responses do not enter advantages, optimizer updates or training token counts.

`validation/step-N.json` stores selected IDs, data hash, coverage, raw BP calls,
game calls and game summaries. Metrics also go to `metrics.jsonl` and the configured
tracker under `eval/`. B/P reports correct counts and denominators, format failures,
truncation, and jointly correct contrasting answers. SP reports completion,
invalid/truncated calls, action frequencies, conditional terminal team and mean
player utilities, and conservative cohort mean-player utility bounds for missing
terminal outcomes. Infrastructure errors fail validation and write a FAILED file;
they are never normal zero-utility outcomes.

Current-team gains are not evidence of improvement against fixed opponents.
The small panel is a trend diagnostic, not a precise generalization estimate.
The existing development data lack P4 private-result-use cases and B3 update
cases; missing diagnostics are explicitly recorded. This panel does not measure
raw-history B-to-P composition. Formal evaluation A remains separate.

Do not add the already inspected CalBench formal 12 cases for checkpoint selection.
CalBench selection would require separate frozen development calendars, a stated
selection criterion and an untouched final test. It can be run less frequently
than native validation, but is not enabled by this change.

For the opt-in reasoning-v4 candidate, the dataset freezes a 45-task panel
(22 B / 23 P) selected to cover its added diagnostics; this overrides the v3
32-task fallback. B3 update and P4 result-use gaps are filled in that candidate.
Matched history/oracle pairs are also reported separately. The development bank
is larger, but it is never evaluated in full during training.
