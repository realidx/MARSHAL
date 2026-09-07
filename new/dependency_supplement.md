# Native functional-dependency supplement

The default supplement now uses `functional-dependency-v1`. The old
`strict-update-value-v2` gate is archived, not required to run. Preserve the
original `full-history-role-context` B/P results and report this supplement
separately.

## Run the frozen set

```bash
bash examples/benac_p/run_dependency_diagnose.sh
```

The script reads `examples/benac_p/fixtures/functional_dependency.json` directly:
**10 native positions**, with three independent source games for each direction
in each source-seed split. Two positions serve both directions. There are ten
unique source games, not twelve independent replications. No random selection
runs by default. Exact labels are revalidated before the usual four preflight
checks and model requests. The vLLM/Hermes configuration and balanced 1024-token
completion plus 128-token truncation-only finalization are unchanged. Use a fresh
output directory; the script supplies one by default.

Nine positions reuse the prior legal fixture pool; one additional query/history
comes from source seed 30040. Selection inspected oracle mechanics only, never
whether a model answer was wrong or repair was positive. These are development
diagnostics. The inherited split names do not make previously examined source
games untouched confirmatory evidence. Estimates describe selected opportunities,
not random-game failure prevalence.

## B→P: consequential partner-judgment sensitivity

Hold the native state, public history and full legal action set fixed. The oracle
checks supported partner types: at least one action optimal under one type must
have strictly positive regret under another. Export the types, action indices
and exact values as a certificate. Other actions can be optimal under both types;
those remain correct. The certificate does not require every optimal tie to
change, nor does it predict an LLM error.

At the root, collect a semantic partner judgment, then compare the same planner
in fresh contexts supplied with its own versus the evidence-supported oracle
judgment. Both P tasks retain identical public history. Report B correctness,
oracle-judgment P regret and paired judgment-repair effect. This measures explicit
judgment assistance; history permits re-inference. A supplied oracle judgment
never reveals an unsupported hidden type. Type-specific values are internal
admission witnesses, not privileged information in the model prompt.

## P→B: forced action-to-evidence contrast

At the same root state and belief, select the first deterministic pair of legal
actions with different expected posterior uncertainty. Both actions must leave a
next actual ego decision on every branch. Execute each action, enumerate **all**
partner-response branches with their hidden-type weights, and ask the same model
to update its semantic judgment and choose its next action. Partner policies
remain deterministic and history-aware; uncertainty comes from private types.

The paired actions are named `low_information` and `high_information` relative to
each other. They are not asserted to be global information extrema or optimal
negotiation actions. The distinct `oracle` arm still maximizes terminal utility
over **every legal action**. All terminal-optimal choices receive zero regret.
The model-chosen first-action arm is measured as before.

Report each forced arm's oracle posterior uncertainty and model judgment accuracy,
plus high-minus-low differences in judgment error and downstream utility. The
information gap is low-arm minus high-arm posterior entropy. A model that
correctly remains uncertain on the low-information arm is fully correct; its
accuracy need not increase on the informative arm. Utility contrasts include
commitment-state changes and do not identify a pure information-mediated effect.
The P→B group establishes action-dependent evidence opportunities; positive
information value or positive model repair is not an admission condition.

## Cost and protocol boundaries

The new builder bypasses `Suite.build`'s exhaustive frozen-belief diagnostics and
does not call the strict certificate. It computes exact native action values,
supported-type sensitivity and the forced evidence pair, then builds tasks only
for the root and selected/model action branches. It does not add game actions,
remove turns, correlate private types, change partner rules, or skip ego response
decisions. Frozen-prior counterfactual searches are not used for admission.
Existing model-judgment counterfactual scores remain secondary and may be marked
unavailable when a judgment contradicts history; they are never zero-filled.

To deliberately mine a fresh set instead of using the frozen set:

```bash
bash examples/benac_p/run_dependency_diagnose.sh --generate --export-only
```

This opt-in path limits queries to two sets per source game and considers at most
three remaining native proposal turns (six goals by default). The candidate seed
budget is bounded; readiness checks both directions in both splits before any
model request. Passing readiness is not guaranteed for a fresh search. Native
oracle values remain exact, with search-budget failures excluded and recorded.
A saved fixture file can be substituted with `--fixtures PATH`.

For a CPU-only engineering check:

```bash
BENAC_DIAGNOSE_OUTPUT_DIR=/tmp/benac-functional-check \
  bash examples/benac_p/run_dependency_diagnose.sh --oracle-check
```

Oracle substitution is not an LLM result. The original strict positive example
`dependency_validation.json` remains available as an illustrative full-loop
case, but is not required for these two cohorts. Its archived certificate can be
checked with `run_full_diagnose.sh --dependency-only --fixtures
examples/benac_p/fixtures/dependency_validation.json --oracle-check`.

Local validation completed 107/107 oracle-substituted tasks, ten complete J
tables and zero unavailable reference costs; all four selection quotas passed.
The oracle updater was exact in both informative and uninformative forced arms.
The 53 relevant tests passed, including score-only replay and rejection of
attempts to invoke the old strict certificate from the functional builder.
Actual task counts can grow when a model chooses a previously unmeasured action.
