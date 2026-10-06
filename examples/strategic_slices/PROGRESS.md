# Active checkpoint — 2026-10-04; continuation — 2026-10-05

2026-10-06 launcher update: the dedicated `terminal_d_soc_v4_delta.json` pins
the v4 manifest and automatically selects 78 pending questions (624 trajectories).
It preserves the user's 32-worker completion-refill scheduler and 4096-token
output budget. The original v2 default config and archives remain unchanged;
use the new `strategic-slices-terminal-D-v4-refill32.tar.gz` transfer bundle and
the manual commands in [TERMINAL_D.md](TERMINAL_D.md). No job is submitted.

## Current work: game mechanism and information acquisition

The user supplied the completed v2 Qwen D results on 2026-10-05: 800 questions,
eight trajectories per question. Evidence is in
[`new/strategic_slices_terminal_d_20261005`](../../new/strategic_slices_terminal_d_20261005/README.md).
The current task improves information-dependent entrance coverage using the
paper-era training bank as a calibration, preserving the v2 checkpoint and its D.
The sections below record earlier milestones; their statements that D was not
run apply to those historical stages. No new remote jobs are authorized here.

The [v4 integration](../../new/local_data/strategic_slices_oracle_consistent_candidates_v4/audit.json)
now keeps 100 parents x 8 questions while adding six distinct certified active
acquisition structural families (five 3p, one 2p). Twenty-five canonical native
neighbors were attempted, 24 certified and one timed out; four positive families
join the two earlier witnesses. These are variations around two base mechanisms,
not six independently invented mechanisms. All six references were reloaded and
independently re-certified, with scalar-BR full/masked checks.

Six unprotected, redundant training parents were replaced, preserving exact
player/round/split quotas and all ten entry-answer groups plus four collective
controls. The 48 new questions protect 12 k=2/3 acquisition windows with S>.05
and C>.1. The other 752 v3 question records are byte-identical. New public-history
channels are unmeasured/null, and new calibrated families remain train-only.
The opt-in initial-terminal-local-decisions-v2 contract permits the certified
2p four-proposal initial entrance, with k<=3 unchanged and full-terminal guards.
The historical default three-proposal API and old records remain intact.

Against the actual v2 model run, 722 question/reference identities are reusable
and 78 need new D (30 from v3 plus 48 new). The explicit subset CLI prepares
624 trajectories, recording exact subset IDs in its resume identity. This is a
reuse plan, not an automatic merge of prior model results. No real model call or
Slurm submission has been made, and no final 100 training slices are selected.
Forty-four tests pass. All 624 delta-run mock trajectories reached native
terminal; completed-run resume generated nothing. A separate 384-trajectory
check covers all 48 new questions and verifies controlled-k handoff. The final
source-snapshot metadata update preserves every runtime input; its manifest
lineage and checksums are recorded in
[`runtime.json`](../../new/local_data/strategic_slices_acquisition_v4_validation/runtime.json).

The optional `goal_structure='multi_action'` mode is now available in
`sample_parent` and the generic build config; default `legacy` identities are
preserved. The frozen terminal candidate pipeline still uses its original mode.
One same-player requirement is added with a separate RNG, keeping catalogues,
priors, schedules, goal modes and all rules identical within each pair. A game
with no eligible addition is unchanged and cannot count as a distinct parent.

The [paired calibration](../../new/local_data/strategic_slices_goal_structure_calibration_v1/summary.json)
completed 8 pairs at a 45-second solver budget per arm: 4/8 old and 4/8 expanded
parents certified, only 3 pairs certified on both sides, no strong first-proposal
acquisition witness among the certified parents. Failed sides have unavailable
values, not zero S. This pilot does not establish a population yield effect;
structure expansion alone is not sufficient. Forty tests pass, including legacy
seed identities and the paired intervention contract. Next recommended milestone:
5–10 distinct positive information-acquisition structural families, then candidate
integration and D on changed questions. The three-proposal entrance limit merits
a separate review for already-certified parents; it has not been changed.
No frozen candidates, references, D records or transfer bundle were modified.

The [native acquisition search](../../new/local_data/strategic_slices_native_acquisition_review_v1/summary.json)
now supplies two independently re-certified initial-state witnesses. Of 130
attempts, 15 initial drafts failed native validation (generator corrected), 94
complete trees were certified, and 21 valid games failed solver certification.
The three-player witness has 18,799 nodes, entrance mass/query probability 1,
k=2 C=.45581 and S=.08333. Its answer changes the next response from REJECT
(AVOID) to ACCEPT (NEUTRAL/WANT), with strict conditional action gaps. The
two-player witness has 143,014 nodes, k=2 C=.375 and S=.10714; full-terminal
S=.21429. It starts four proposals before terminal and is therefore only a
mechanism prototype under the present three-proposal entrance rule. Both saved
profiles were reloaded, re-certified and checked with an independent scalar BR.

Six three-player controls all certify: prior changes retain S=.0625–.125;
removing the second focal action from the bonus goal yields S=0; making that
goal linear gives S=.02778; adding a public WANT to the avoid-only goal leaves
S=.08333. These findings concern selected profiles and include equilibrium
selection changes. The generator currently excludes multiple requirements from
the same player within one goal, despite their legality in the native game.
Both witnesses include that missing structure. This is a concrete calibration
direction, not a claim that public-WANT anchors universally suppress information.
Fixtures and diagnostic generation/verification/control scripts are preserved;
36 tests passed at that stage, without changing production rules, generator,
candidates, references, or D. The subsequent opt-in generator extension is
recorded above. The two base structures and their prior variants are not a new corpus.

The [mechanism diagnostic](../../new/local_data/strategic_slices_mechanism_diagnostic_v1/conclusions.json)
adds six convenience parents with fixed partner profiles: 249 free single-slot
information comparisons yield only three positive gains (max .03661), all in
one three-player parent. Free revelation of every partner type has zero early
gain in the five selected two-player parents and up to .09117 in the three-player
case. Removing the opportunity cost alone is therefore not a sufficient
explanation for this sample. These are information interventions, not modified
game equilibria. Legal unilateral offers, rejection without extra penalties,
linear payoff separability (37 parents), public-WANT anchors and repeated turn
order are structural hypotheses; their individual causal effects remain open.
The old external-PASS fixture retains S=.25, but its full initial reference
failed certification twice. The native schedule comparison is incomplete and
does not establish a schedule effect. Production artifacts are unchanged;
34 regression tests and independent signal-conditioned BR checks passed.

The [early-investigation audit](../../new/local_data/strategic_slices_early_investigation_v1/summary.json)
is complete: all 100 parents, 250 parent/player pairs, and 8,357 reachable first
proposal information cells, including 88 excluded by the three-proposal entrance
neighborhood. Full-terminal focal best responses show 2,573 query/non-query ties,
5,783 query-inferior cells, and just one strict advantage of .0138533; none exceed
.05. Prohibiting all future focal investigations preserves optimum value in all
but that same cell. Even its gain survives masking the selected private answer
through terminal (S=0), so it is an action/continuation advantage, not evidence of
positive private-answer value. Partners remain on the same saved oracle profile.
528 cells have both an unknown query answer and a subsequent focal proposal;
none have strict acquisition-action advantage. The active-acquisition coverage
gap is therefore still open after restoring early entrances and full lookahead.
No dataset, game, reference, or model job was changed by this audit. 31 tests and
independent native subtree/action-removal checks passed.

The [v3 candidate revision](../../new/local_data/strategic_slices_oracle_consistent_candidates_v3/audit.json)
keeps all 100 original parents/references/splits and exactly eight questions each.
An exhaustive reachable-entrance scan found 220 strong existing-answer contrasts
in ten parents, among 9,209 measured groups. None of their members occurred in
the original 800-question subset. The revision retains ten complete must-change
groups (30 fixed-information questions; train 9 groups, test 1, validation 0).
Selected conditional entry-answer S ranges from .05357 to .31884. Query-acquisition
S is unchanged. A group S is not a singleton label and is not counted 30 times.

770 questions are unchanged; 30 require new D. `D_reuse.json` records this mapping,
but the existing v2 run cannot be resumed directly against a changed manifest.
The revision independently checks selected S through masked dynamic programming
and verifies new member C/posteriors against the saved oracle. No new equilibrium
solves, model calls, training, or final 100-question selection were performed.
See [definitions and selection](ENTRY_INFORMATION.md#existing-private-answers-one-decision-entry-contrasts-2026-10-05).

## Historical milestone: prepared base-model D pipeline

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
