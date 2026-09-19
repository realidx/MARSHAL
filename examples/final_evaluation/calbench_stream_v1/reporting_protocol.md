# CalBench small-model sequential evaluation v1

This is a small-model adaptation, not a reproduction of the paper's aggregate
benchmark score. Native rules, observations, DM contact activation, transactional
calendar updates and consistency checks are unchanged. Source: CalBench paper
https://arxiv.org/html/2605.09823v3 and the pinned source manifest.

## Frozen design

24 games per model: four conditions × two errand-cost regimes × three scenario
seeds (2026091901, 2026091902, 2026091903). Each game has four homogeneous agents,
eight calendar slots and three sequential incoming meetings. Participant sets
rotate through 012, 123, 023. No initial meetings are preloaded; any meeting
commitments are created during this run. Future meetings and evaluator references
are not inserted into model observations.

| Condition | Native generator density | Blocked errands per player | Purpose |
|---|---:|---:|---|
| loose | .6 | 0 | Sequential scheduling with private displacement costs |
| dense | 1.0 | 0 | Less spare capacity and persistent state |
| blocked | 1.0 | 2 | Immovable constraints alongside movable errands |
| replan | Authored control | Varies | Revisit a self-created meeting and contact a former participant |

Uniform errands cost 1; varied errands use a custom integer cost distribution 1–8; moving meetings costs 1 per
participant. Agent calendar displays, engine deductions and enumerated references
all use these actual numeric costs without the paper's alternate cost mapping. Native generator density is applied to residual capacity after
reserving meeting/blocked slots, **not raw occupied calendar fraction**.
The replan cost variants are nuisance controls: their optimal path costs zero;
the useful signal is coordination, not a cost tradeoff. The three seeds change
private occupancy/costs; they are not merely three stochastic decodes. Paired
cost conditions/shared seeds are not independent structural families.

In the replan control, placing meeting 1 at slot 0 forces its relocation to slot 1
when meeting 2 arrives. Player 0 is then outside the new meeting and must be
contacted. Placing meeting 1 at slot 1 initially avoids relocation, so the full
run does not force or isolate replanning ability in every trajectory. Report how
often the model actually encounters and resolves that branch. Native reference
replays test both contact and missing-contact paths.

Temperature is 0. Each meeting allows four communication turns per participant,
one decision retry, no fallback and no reflection. DM only. Output/context
budgets and thinking setting must be matched across compared models. Primary output
budget is frozen at **4096 tokens**, context 32768. The 768-token protocol is a
separate diagnostic condition; do not pool the two budgets. No communication-topology
sweep or different team sizes is claimed. Reflection-calibrated VPS is **not measured (null)**. Native privacy defaults
(such as privacy_score=1) are not measured privacy results. Raw metrics remain
archived, but the native composite headline is not a paper-comparable score.
DM counts and character volume are communication observables, not privacy measures.
No disclosure estimator is currently installed, so disclosure is also marked not
measured rather than inferred from message volume.

## Scoring and verification

Report by condition: fraction of meetings scheduled, full-stream completion,
realized total cost (including incomplete games), strict-format error rate and
truncation rate. Separately retain native schema rejections, state-dependent
action failures, new-meeting slot mismatches, and old-meeting inconsistency.
Retries never erase earlier failures. Old-meeting failures count once per
meeting × round, rather than once per affected participant. Envelope failures
and schema rejections have different denominators and must not be added together.
Only report verified full-stream excess cost for complete games; report missing
values and completion rate together. Infrastructure failures are separate.

All 336 distinct final slot assignments are enumerated. Initial errand
displacements lower-bound cost; an actual native sequential replay must attain
that bound. This is a **hindsight** reference, not a claim that an online player
can anticipate hidden future meetings. Every case and replay certificate is
hashed in calbench_stream_v1. No model outcomes were used for selection. The 336 candidates are not all feasible.

Old `--suite formal` remains the historical 12-case suite. New `--suite stream`
is separate and should not be pooled with old scores. Avoid choosing further
scenarios or checkpoints based on performance on this frozen test suite.

## Run

Use the existing local launcher with `--suite stream`; local/API routes and
parallel games continue to work. On SoC, for example:

```bash
bash examples/final_evaluation/submit_calbench_soc.sh h100-96 q0 stream 4096
# Substitute an absolute Hugging Face checkpoint directory for q0 as needed.
python -m examples.final_evaluation.calbench_stream --verify examples/final_evaluation/calbench_stream_v1
```

This change validates native execution on CPU; it does not itself run a GPU model.

## Interpretation and trace audit (reporting revision 2)

This evaluates **homogeneous-team transfer**: replacing all four teammates with
the trained model. It does not isolate improvement of one agent facing fixed
partners. Include B/P-only and SP-only as the current training comparisons.
24 cases are not 24 independent structures; report matched case outcomes and
differences, grouped by condition. Players and meetings are not independent samples.

Full-stream completion requires all requested meetings to remain in exactly one
common slot across their participants in final calendars, absent from nonmembers,
and preservation of blocked items. Native historical success counts remain raw
trace data. Full-stream excess cost is null unless final completion passes.

Replan results report four counts: entered branch, contacted the old participant
among entrants, consistently revised among contacted entrants, and not entered.
Not entered is neither failure nor proof of replanning. Choosing slot 0 initially
is not automatically irrational because future meetings are hidden.

Audit an existing run without model calls (preserves all original outputs):

```bash
python -m examples.final_evaluation.calbench_stream_metrics /path/to/run/evaluation > stream-audit.json
```

Use the directory containing execution_protocol.json for protocol attribution.
Missing traces/infrastructure failures remain explicitly missing. Raw native
headline scores are retained for debugging only, not the primary comparison.
