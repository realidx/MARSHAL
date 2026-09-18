# Social reasoning curriculum v4 — candidate

This is an offline, CPU-checked candidate, not a claim of improved learning.
The default training release remains v3. Select this pack explicitly with
`SOCIAL_DATA_DIR=examples/social_mixed/data_reasoning_v4_candidate`.
The collector and validator route history tasks through `reasoning_requests.py`;
using the legacy BP request builder directly is not supported for those tasks.
No reward, optimizer, rollout token cap or grounding identifier changes are made.

## What changed

- B/P train: 426 → 563; development bank: 275 → 471. These are bank sizes,
  **not periodic evaluation sizes**. Periodic evaluation is frozen at 45 tasks
  (22 B + 23 P), one answer each, plus eight current-model self-play games.
- Added three-player B/P geometries (four train, four dev), with three unresolved
  preferences and legally imposed existing commitments. Binary and linear variants
  stay within one geometry's split. Further decision-relevance search adds cases
  under the same structural split exclusion rules.
- Added B judgments at actual evidence boundaries, including updates and unchanged
  judgments. Development now contains B3 updates and P4 investigation-result use.
- Added native-history P decisions and paired exact-joint-posterior conditions.
  The same history, private observations, policy and acceptable action set are used
  in each pair. Raw-history requests contain no supplied posterior or hidden world.
- Critically, merely containing history is insufficient. Most initial candidates
  did not change acceptable actions when behavioral evidence was ignored. They
  are controls; new train controls are limited to two per mode/player-count cell.
  Four train and five dev public-history decision points change the acceptable
  set. They also have separate, linked B questions. These sets may overlap the
  prior-only sets; this is not a guarantee that ignoring history always fails.
- Self-play: 96 → 108 training resets, 32 → 36 dev resets. The 12/4 additions are
  independent three-player geometries with 3–4 rounds, alternating binary/linear.
  Every addition was replayed through native rules to termination with utility
  verification. Initial states remain empty; bound-state BP exercises complement
  the naturally evolving states of full-game self-play.

## Validation and limitations

The small periodic panel preserves full contrast groups and covers available
kernel/mode, B full/reduced support, B3 update/maintain, P4 query/no-query/last-turn/
result use, raw/supplied belief, and player-count cells. IDs and coverage are saved.
No Q0 is loaded. Entire development banks are retained for offline diagnostics.

`preflight.json` verifies hashes, binary/linear-only scope, structural split
separation and actual sampling of all training tasks over 512 scheduled updates.
`coverage_report.json` also reports the shorter 194-update schedule: 556/563 tasks
appear, including all four new history-sensitive decisions and all new result-use
pairs. This does not mean all tasks receive repeated or useful gradient feedback.

Formal A and CalBench trajectories/outcomes were not used to generate labels.
A's geometry IDs were used only to exclude newly generated structures. Existing
training geometries that A intentionally reused as ID remain existing training
geometries. The inherited BP test file is unchanged.

**Still open:** no useful OFFER-acquisition premium was certified by the inspected
P4 sources. Do not call arbitrary random SP scenes “information-seeking lessons.”
The candidate teaches response-conditioned inference and action, but does not
finish that strategic acquisition subtask. Teacher cycling failures are recorded
in the search audit, not converted into labels. All teacher-model robustness
limitations remain.

## Reproduce the offline build

Use Python with the repository's CPU dependencies, from the repository root:

```bash
python -m training.social_mixed.prepare_reasoning_v4
python -m training.social_mixed.expand_reasoning_geometry
python -m training.social_mixed.expand_feedback_v4
python -m training.social_mixed.search_history_decisions_v4
python -m training.social_mixed.finalize_reasoning_v4
python -m training.social_mixed.audit_reasoning_v4
SOCIAL_DATA_DIR=examples/social_mixed/data_reasoning_v4_candidate \
  python -m training.social_mixed.preflight
python -m unittest training.social_mixed.test_reasoning_v4
```

Candidate rebuilding is explicit and overwrites candidate artifacts only. Source
releases, formal evaluation artifacts, training checkpoints and results are not
rewritten. Rebuilding or changing training datasets is not a continuation of an
old dataset-identical experiment.
