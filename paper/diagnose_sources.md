# Diagnose: native results and provenance

Main source: `runs/benac_native_endgame/functional-dependency-retry3-20260908-064709`.
Frozen suite: `functional-dependency-v1`; prompt: `native-endgame-diagnose-v5-role-context`;
model: `Qwen/Qwen3-4B-Instruct-2507`, temperature zero. Ten positions from ten
source games; each six-game cohort includes three games from each retained
source partition. Two positions belong to both directions. Selection did not
inspect model answers. The partitions were reused during development and are
not untouched confirmation sets.

The main text reports both partitions together **within each cohort**, rather
than presenting one reused partition as a held-out test. The appendix retains
all four split-by-cohort cells. `diagnose_results.json` records the aggregated
values, source hashes, coverage, controls and six paired action indices.
Aggregation uses `benac_p.diagnose_suite.cluster_summary`, 2000 game-bootstrap
resamples, RNG seed 0. No cross-cohort pooling is used.

| Manuscript item | Source |
|---|---|
| Table 1A: B→P 6/6 certified cases | `certificates.json`: B→P members, `functional.belief_to_planning`; action optimal under left singleton has positive regret under right singleton |
| Table 1A: P→B 6/6 certified cases | `certificates.json`: P→B members, `functional.planning_to_belief`; positive exact information gap |
| Table 1A: entropy 1.585 / 0.667 | `scores.json / active`: `forced_low_posterior_entropy`, `forced_high_posterior_entropy` |
| B exact, P regret, B repair | `scores.json / cases`: cohort roots; `belief_exact`, `OL`, `belief_repair` |
| Changed actions: 3/6 | `answers.json`: root `plan_model` versus `plan_oracle`, B→P cohort |
| Forced evidence gap | `scores.json / active / forced_information_gap` |
| Forced-arm exactness | `forced_low_belief_exact`, `forced_high_belief_exact` |
| Paired exactness difference | `forced_belief_exact_delta`, scaled to percentage points |
| Paired utility contrasts | `forced_reference_utility_delta`, `forced_model_second_decision_then_reference_delta` |
| Per-partition appendix table | `summary.json / conditions` |
| 127 tasks, 230.8 tokens, no truncation | `protocol_summary.json` |
| 3/4 semantic controls and cached resume | `belief_preflight_*`, `preflight_policy_change.json` |

Independent replay rebuilt all 127 task payload hashes, oracle labels,
intervention branches and scores exactly. The first-pass system/tool hashes
also match the manifest. One secondary counterfactual root reference score is
undefined for an impossible type/history combination; direct model-regret
comparisons remain valid. Ten auxiliary J tables are complete, but all their
updater-repair values are zero. They are not presented as evidence of positive
information-mediated utility.

The B→P intervention changes actions on seeds 30005, 30016 and 30018. Two changes
preserve utility; seed 30018 increases regret by 2/3. Thus behavioral coupling
and beneficial repair are different empirical statements. P→B is established
at the action-to-evidence interface through exact branch enumeration, not by
assuming that changed oracle supports imply changed internal LLM beliefs.

Table 1 now separates oracle-certified task dependencies (panel A) from model
error measurements (panel B). The 6/6 entries are selection properties, never
model success rates or prevalence estimates. B→P singleton type probes are
internal oracle calculations; model P receives the evidence-supported judgment,
which can remain uncertain. Action changes, signed repair, and the paired B
accuracy difference remain reported as supplementary joint-response observations.
The claim is model errors at two interfaces within tasks that couple their
computations, not causal amplification between internal model weaknesses.

Preceding native baseline: `runs/benac_native_endgame/full-history-role-context`.
Its 36 positions, full labels and scores were independently rebuilt and matched.
The appendix quotes its six confirmation unknown/relevant primary cases only:
B exact 1/6, reference-judgment P regret 2/3. It is not pooled with the latest
run. Nine frozen positions are reused; the tenth is a new query/history from
source game 30040, already represented in the baseline. The previous semantic
three-stage experiment is historical and supplies no current manuscript result.

Updated files:

- `diagnose.tex`: native methodology, capability errors, functional dependencies,
  signed interventions and implications for targeted training.
- `diagnose_appendix.tex`: all position IDs, exact procedures, controls,
  aggregation, per-partition values and secondary score limits.
- `preliminaries.tex`: replaces the obsolete passive snapshot-response oracle
  and automatic-approval recursion with the implemented active history-aware
  terminal best response and native ego-decision-window solver.

Scope: these data support task-level B/P errors and functional dependencies
among explicit judgments, actions and evidence. They do not establish separate
internal neural modules, universally beneficial repair, end-to-end long-horizon
LLM competence, or transfer. The failed known-copy control limits attribution of
belief errors exclusively to strategic inference. A causal effect of changing
an explicit input or action is not identification of an internal cognitive
mechanism.

Worked example: `native-30040-g6-d2`, one of the existing six P→B cases.
Root state/history/goals/preferences are taken from its `root/plan_oracle`
task. The two arms are `low_information` (ordinary offer, action index 7)
and `high_information` (menu, index 11). The menu CHOOSE_1 case is
`after_655f72f82fc2/1`: oracle support AVOID, model answer WANT/NEUTRAL.
The CHOOSE_2 case is `/0`: oracle support WANT/NEUTRAL. Subsequent ego
REJECT/ACCEPT values are [0,0] and [1,2], respectively, from saved labels.
The appendix response-value rows [1,1,2], [0,1,1], [0,1,0] for P2 were separately
recomputed with the existing RationalPartner search at the pending menu under
its fixed reference continuation. No new model requests or game rules were used.
