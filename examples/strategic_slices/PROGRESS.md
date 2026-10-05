# Active checkpoint — 2026-10-04; continuation — 2026-10-05

## Prepared next step: base-model D pipeline

The user requested a complete SoC pipeline using Qwen3-4B-Instruct, with **no
automatic job submission**. [TERMINAL_D.md](TERMINAL_D.md) documents the launcher,
historical environment provenance, offline bundle and explicit manual commands.
The configured checkpoint is Qwen3-4B-Instruct-2507, matching recorded SoC runs.
Each of 800 candidates receives eight independent resets/rollouts, not two groups.
The current user-requested serving profile is **16 workers and 4,096 output
tokens** (context remains 16,384); the full mock below used the earlier 4-worker,
1,024-output-token profile. Updated defaults receive local regression/config checks.
Partners and post-k focal actions use the saved initial terminal reference.
The pipeline reports D, D/C, uncertainty, protocol failures and observed signal
diagnostics; it performs no training or final 100-slice selection.

The new CPU runtime/transport/recovery tests plus candidate/oracle consistency
regressions passed (22 tests). The full CPU mock completed all 6,400 trajectories;
independent native replay verified all final utilities, 10,261 model decisions
and 1,269 post-k focal reference decisions, including all 32 collective-control
trajectories. Complete-run resume made zero new generation calls. The transfer
archive passed all 1,045 file hashes and an offline check from an isolated extracted
directory. [Local validation record](../../new/local_data/strategic_slices_terminal_d_validation_v1.json).
These are engineering checks, not model D or learning evidence.
Actual GPU/model execution remains untested locally.
No Slurm submission or remote operation has been performed.

## Completed working milestone

[Current balanced subset](../../new/local_data/strategic_slices_oracle_consistent_candidates_v2/REPORT.md):
**100 unchanged parents, exactly 8 candidates per parent, 800 candidates.**
This is an unchanged-record subset of the audited v1 pool below. All references,
parents, splits and C/S values are preserved; the original 1,596-row pool remains available.
Exhaustive within-parent selection balances player counts, then k, then decision
kind; diversity and cumulative distribution break ties. All available player/k/kind
categories and all four collective controls are preserved. See `balance.json` and
`selection_ledger.jsonl` for the complete policy, counts and selected IDs.

- k=1/2/3: **365/279/156**; proposal/response: **396/404**.
- Two-player seats 0/1: **200/200**; three-player seats 0/1/2: **136/130/134**.
- All 30 multi-round parents retain k=2 and k=3. There are 728 distinct public
  entrance nodes and 812 member records (collective controls have multiple members).
- Subset integrity and loader validation passed. Original independent audit
  evidence is inherited, not presented as a new 800-row solver/C/S audit. No D run.

### Original verified pool (preserved checkpoint)

[Verified candidate pool and report](../../new/local_data/strategic_slices_oracle_consistent_candidates_v1/REPORT.md):
**100 distinct parents, 62 structural families, 100 full initial terminal references,
1,596 candidates across 1,268 distinct public entrance nodes.**

All 100 references independently re-certified; 1,608 candidate members had their
C/V values and prefix posteriors rechecked; 104 S records were remeasured.
Maximum retained-window deviation over the reference is approximately 1.60e-9.
The final related regression suite passed **62 tests**.

Coverage: 30 two-player/two-round, 20 two-player/one-round, and 50 three-player/one-round
parents. Every multi-round parent has retained k=2 and k=3 candidates. No D was run;
the final 100 slices are **not** selected. The working 30-parent multi-round floor
does not establish the final research coverage requirement.

## Objective

Collect 100 canonically distinct parent games, retaining multiple representative
oracle-consistent slice candidates per parent. Final selection of 100 slices
requires future D evaluation. **Do not run D in this attempt.**

Every parent uses one saved, independently certified initial-state terminal
profile. Prefix likelihoods, entrance posteriors, partner policies and focal
continuation all refer to that profile. No random-prefix belief reset, independent
entrance re-solving, cutoff payoff substitution, or support shrinkage.

## Starting checkpoint

[Checkpoint metadata](../../new/local_data/strategic_slices_checkpoint_20261004_before_optimization/checkpoint.json)
and its SHA-256-addressed archive preserve the pre-optimization code and active
candidate corpus. Unrelated working-tree changes are excluded.

- 70 selectable parents: 28 two-player and 42 three-player.
- Only one multi-round parent; 1,116 retained candidate windows.
- These are generated/review candidates, not a fully audited final dataset.
- No retained row currently exceeds the S > .05 information-positive threshold.
  This must remain visible as a mechanism-coverage limitation.
- The previous 47-parent mixed-reference corpus is historical and is not the
  current progress count.

## Current attempt

New results are written to
`new/local_data/strategic_slices_oracle_consistent_search_v2/`; v1 is preserved.

Working generation coverage target: at least **30 multi-round parents**, where
multi-round means at least two complete proposal rounds. This is an operational
target chosen for this attempt, **not a quota previously fixed by the user**.
The existing 50/50 player balance, canonical duplicate checks, family cap of 8,
and up to 16 candidates per parent applied to the original generation pool.
The subsequent user-requested balanced subset retains exactly 8 per parent.
Generation selection prioritizes multi-round
parents; packaging refuses to complete if the coverage floor is unmet.
Three-player multi-round coverage and horizons beyond two rounds remain open.
Native round count alone does not demonstrate multi-step strategic difficulty;
the retained k and decision-capacity distribution must also be reviewed.

Short-parent expansion was held while the multi-round search was validated.
After reaching 50 two-player / 42 three-player parents with 25 multi-round
parents, short sampling resumed only to fill the three-player quota. Two-player
short jobs skip automatically at quota; the multi-round packaging floor remains.
The first new batch comprises 24
independently seeded two-player, two-round native games, using the existing
generator without altering their supported worlds or payoffs after sampling.
Budget: 240s solver, 8 ordered sweeps per start, 8,192 joint cells; each accepted
profile still requires the original complete scalar certification and native audit.

That first batch finished with **16 verified and measured parents / 8 uncertified**,
and no solver timeouts. Canonical duplicates and family caps are applied after
measurement, so successful attempts do not each add a distinct selected parent.
Further independently seeded batches filled the working count/coverage requirements;
generation stopped at a completed batch boundary once both were met.

## Verified engineering progress

A vectorized local-support/tie screen rejects clearly invalid candidates before
full certification. It batches array operations, not histories or information
sets. Passing the screen never grants a certificate. The original scalar
`certify_policy` and its numerical tolerances remain unchanged.

- Existing failed two-round case 47: 90.62s before versus 20.73s with screening
  at the same two-sweep cap; both reject the candidate.
- Case 47 with eight ordered sweeps: 20.18s including full certification/native
  audit, now certified. Re-measurement produced 16 candidate windows.
- Case 41 remains certified; its saved policy hash is exactly unchanged in the
  two-sweep comparison. Total time fell from 20.07s to 16.31s.
- Cases 37 and 48 still failed certification with eight sweeps. Optimization is
  not a claim of general convergence.
- Final candidate-screen/equilibrium/bounded/oracle/distribution/information suite:
  62 unique tests passed, including restoration with nondefault search budgets.

Results and source snapshots:
[optimization manifest](../../new/local_data/strategic_slices_solver_optimization_v1/manifest.json).

## Remaining research questions

- Whether this preliminary coverage is sufficient: three-player multi-round and
  horizons longer than two rounds are not covered.
- Strong information value: no measured S exceeds .05. Four collective records
  have small positive S (maximum .015334); other entry-history channels remain
  unmeasured/null. These limits are recorded in the manifest, not hidden by the count.
- Model usefulness and long-horizon generalization remain unmeasured. D and the
  final 100-slice selection are explicitly deferred until requested.
