# Diagnose: result provenance and author notes

**Historical restricted-protocol results.** The source run below predates the
native endgame redesign. Its action catalogue/schedule and preference coupling
do not establish diagnosis in the original game. The current native methodology
is documented in `new/native_endgame_diagnose.md`; real-model results must be
rerun before replacing or interpreting the paper tables as native-game evidence.

Source run: `runs/benac_semantic_diagnose/full-retry-827269`.
Semantic protocol: `semantic-interaction-loop-v2`, belief prompt `episode-prior-v2`.
Model: `Qwen/Qwen3-4B-Instruct-2507`; seed 20000; 12 matched bundles, three conditions each.

- `diagnose.tex` is included by `main.tex` under Diagnose.
- `diagnose_appendix.tex` is included after `\appendix`.
- Preliminaries now describes the actual finite-support deterministic diagnostic
  partners/reference planner; the old stochastic kernel and perfect-information
  debug policy are not the policies used for these results.

The main table uses `summary.json / confirmation / unknown_relevant`:

| Manuscript measure | Summary field |
|---|---|
| Post-response B exact | `belief_exact` |
| Ruled-out labels retained | `unsupported_possibilities` |
| Initial P regret | `root_planning_regret` |
| Post-response P regret | `OL` |
| B repair | `belief_repair` |
| Channel information gain from repair | `channel_information_repair` |
| Updater repair after reference action | `updater_repair_oracle_action` |
| Action repair with model updater | `chooser_repair` |

The two factorial tables use `R` and `J` at the same path. Control means use the
corresponding `known` and `unknown_irrelevant` paths. Initial B is 100% in all
three confirmation conditions. Mean model B exact over each of the two forced
action arms is 2/9, computed from `scores.json / active` by selecting confirmation
unknown_relevant games and averaging `arms.oracle.belief_exact` and
`arms.model.belief_exact` separately. Their evidence quality differs; agreement
with a larger admissible set is not the same as identifying a hidden type.
The illustrative error is
`b20006/unknown_relevant/after_assess_menu/CHOOSE_1/belief`; it is paraphrased,
not presented as a representative frequency estimate.

Validation: regenerated all 486 payload fingerprints, oracle labels, scores and
summaries from the archived model answers and matched the stored artifacts.
Four preflight calls are separate from the 486 diagnostic tasks and 517 requests.
The protocol summary reports 31 initial truncations, 31 recovered submissions,
486 first passes with reasoning, and 146553 total completion tokens. Preflight
adds 579 completion tokens in four requests.

Claim boundaries retained in the manuscript:

- B failure after evidence, P failure with correct B (strongest at the initial
  interaction), and beneficial B repair are supported on these selected instances.
- P-to-evidence intervention is supported; action-only downstream utility benefit
  remains uncertain, and model judgment exact does not improve between action arms.
- Reference-action updater repair and R-table judgment cost reuse the same
  post-response evidence; they are not independent replications.
- The named confirmation split has been reused during interface development;
  it is not an untouched generalization test. Six bundles per condition are
  the sampling units; these are descriptive within-family bootstrap intervals.
- Results concern one model and a restricted three-stage task family. Training
  improvements, transfer, general long-horizon competence and model-population
  prevalence are not established by this section.

LaTeX builds successfully without overfull boxes. Remaining missing citations
(`Hinton06`, `Bengio+chapter2007`, `goodfellow2016deep`) occur in the pre-existing
conference-template instructions, outside the new Diagnose material.
