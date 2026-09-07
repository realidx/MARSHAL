# Native BENAC-P endgame diagnosis

`run_full_diagnose.sh` runs the native endgame suite. The previous semantic suite
remains available as `run_legacy_semantic_diagnose.sh`; its results used a modified
protocol and must not be reported as results of this native implementation.

## Game and information boundaries

Candidates come from the original three-player generator. Each original round
contains a shuffled permutation of all players. Legal public histories are
replayed from zero commitments. Ego and queried partner roles vary across seeds;
player preferences are not tied. OFFER, MENU, PASS and native responses retain
GameState legality and binding commitment transitions. Every legal offer and
pair menu remains available; there are no preparation or assessment actions.

The initial interface isolates one unknown want/neutral/avoid preference while
supplying the other preferences. Optional `--unknown-goals 2` uses a Cartesian
product of semantic profiles, without probabilities. These are selected,
conditional diagnostic positions, not estimates over all random games.

Partners actively propose and respond. Their deterministic policy is certified
as terminal-utility optimal against an explicitly declared fixed reference
continuation. Reference responders maximize immediate satisfied-goal utility;
reference proposers choose the best immediate ordinary offer assuming acceptance,
with reject/pass winning ties. Actual oracle partners search all native actions,
including menus. This is a best response to a specified continuation, not an
equilibrium or a guarantee against arbitrary future LLM behavior.

All P tasks include the full public history, including a pending proposal, the
current physical state, initial public possibilities and a supplied semantic
partner judgment. B→P pairs use identical fresh contexts except for that judgment.
The old history-free universal-policy certificate is no longer a selection gate.
Active partners infer from public history and their own preferences, then compute
an exact terminal best response to the declared fixed reference continuation.
No realized private matrix is available to them. If the immediate-reference action
is terminal-optimal it breaks the tie; otherwise native enumeration breaks ties.

## Four measurements

- **B:** infer the semantic possibility set from the initial public possibilities
  and legal history. Score exact sets, unsupported possibilities and false
  exclusions. Empty history does not restore excluded population types.
- **P:** select a native action given the correct evidence-supported judgment.
  Score terminal utility regret against exact reference planning. This is
  oracle-judgment-assisted planning, not isolation of internal B computation.
- **B→P:** fresh P contexts receive either model or corrected judgment in the same
  format, with identical public history, state and actions, without old reasoning. Export the
  belief-by-planner R table. Repair never reveals an unresolved hidden type.
  Models may re-infer beliefs from history: a null explicit-judgment repair
  effect does not demonstrate absence of B→P dependence.
- **P→B:** force the model or terminal-utility-optimal first action, enumerate all
  possible partner evidence, and apply both oracle and model updates. Export the
  chooser-by-updater J table, posterior uncertainty and downstream utility.
  Additional high/low-information actions certify channel opportunities.

Reference actions maximize terminal utility, not information. Ego actions are
interventions, not rational evidence. All response branches retain their original
weights; missing answers are reported as missing, never renormalized away.

Each position measures at most two actual ego decisions: the root and the next
native ego decision after partner play. ACCEPT/REJECT/CHOOSE count too and are
never folded away. All native turns execute; decisions after the second measured
action use reference continuation. Thus scores are not full end-to-end LLM games.

Menu choices change commitments as well as evidence. Utility repair alone does
not establish information mediation. Report channel changes separately from
updater errors; same-action judgment-update gains can be zero. A common optimal
menu across types is allowed: different actions are demanded only by strict
utility differences.

## Selection and uncertainty

The miner selects known, unknown-relevant and unknown-irrelevant positions.
Relevance means an action optimal for one possible type can be strictly suboptimal
for another. A perfect-information value gap is a secondary readout, not the
relevance definition. Selected roots have menus and one or two remaining ego proposal
turns. The relevant stratum additionally requires evidence before a further
measured ego decision; known controls need not retain an unnecessary second
proposal turn. Relevant cases must include continuing evidence and an active partner
proposal; each split also needs an evidence-update case. Potential wrong-judgment
reference cost is a secondary witness, not a selection prerequisite.

Seed parity preassigns discovery/confirmation before model evaluation. Default
quota is six independent source games per condition per split. Positions from the
same original game are clustered for uncertainty estimates. The three conditions
are generator strata, not exactly matched counterfactual triples; cross-condition
comparisons are descriptive. B→P and P→B interventions are paired within position.
Selection uses oracle properties only, never model failures.

The default miner uses positions with at most three original proposal turns left
(`--max-remaining-turns`, up to six). This reduces exact search cost by selecting
later legal histories; it does not truncate or remove game turns.

Search limits produce exclusions rather than approximate labels. If the candidate
budget cannot fill the quota, the run saves selection/readiness diagnostics and
stops before model requests. The default 64-seed budget is a resource limit, not a
guarantee of a complete corpus. Increase candidate seeds or exact-search budget in
a fresh output directory if required. Completed seed selection is resumable with
unchanged settings.

## Running

Use the existing remote vLLM/Hermes environment and model/base URL variables:

```bash
bash examples/benac_p/run_full_diagnose.sh
```

The script mines/certifies positions, performs four separate empty-history B
preflight checks, runs all four blocks, and writes `report.md`, `summary.json`,
`scores.json`, tasks, answers, oracle labels, certificates and selection provenance.
Incorrect semantic answers are retained, not retried until correct. Brief balanced
reasoning uses the existing 1024-token cap plus bounded 128-token finalization.

For a reproducible CPU engineering check (six positions; **not a research sample
or real-model result**):

```bash
bash examples/benac_p/run_full_diagnose.sh \
  --fixtures examples/benac_p/fixtures/native_validation.json \
  --min-games-per-condition 1 --oracle-check
```

Set `BENAC_DIAGNOSE_OUTPUT_DIR` to reuse an output directory and pass `--resume`
with identical arguments. `--score-only` scores saved answers; `--score-max-nodes`
can increase the separate counterfactual scoring budget. `--export-only` exports
without model calls. Synthetic runs must retain `--oracle-check` on resume/score.
Never interpret synthetic oracle checks as evidence of an LLM weakness.

## Counterfactual reference boundary

With history-aware partners, an incorrect supplied judgment may assert a private
type incompatible with public history. If this makes reference forecasting
undefined, the corresponding R_LO and J entries are explicitly unavailable.
They are never zero-filled and branches are not renormalized. Direct paired LLM
planning regret, semantic belief quality and evidence-channel measurements remain
well defined. This is recorded in the report and measurement coverage.

## Version and validation

The suite version is `native-endgame-diagnose-v5-role-context`. Use a fresh output
directory and newly selected fixtures: old partner-policy histories and answers
must not be resumed under the new policy. The validation fixture is an engineering
check, not a research-sized sample or a real-model result.

The reselected six-position history-aware validation pack passes the one-game
per-condition/per-split gate. Its 49/49 synthetic tasks are valid, all R regrets
are zero, and all six J tables agree across synthetic oracle/model substitutes.
This does not establish model performance or fill the default six-game quota.

## Role-context prompt correction

The model sees an explicit `role_context` identifying the ego, assessed partner
and assessed goals. `ego_preferences` names its owner; player and goal references
use P/G labels consistently. Goal formulas describe achievement conditions,
whereas preference labels describe a particular player's utility. B starts from
the named partner's initial possibility set; empty history preserves that set.
Preflight and formal B use the same wording. Exported `belief_preflight_tasks.json`
and `prompt_protocol.json` preserve the actual inputs and system instructions.
Semantic errors still stop preflight and are retained without retries.

The existing 36 selected positions can be reused: the prompt correction changes
neither the oracle policy nor labels. Use a fresh output directory:

```bash
BENAC_DIAGNOSE_OUTPUT_DIR=runs/benac_native_endgame/full-history-role-context \
  bash examples/benac_p/run_full_diagnose.sh \
  --fixtures runs/benac_native_endgame/full-history/fixtures.json
```

This bypasses candidate mining, then rechecks the saved positions, runs the four
preflight requests and, if they pass, starts the full diagnosis. Do not use
`--resume` with the old prompt's output directory. Prompt clarity has local
regression coverage; real-model improvement still requires the remote run.
