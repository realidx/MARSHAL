# Native dependency supplement

The `full-history-role-context` run remains the original B/P measurement. Its
updater-repair opportunities were degenerate: posterior updates did not improve
the reference continuation action. This supplement selects a separate cohort
where an update can change a consequential decision. Selection uses only the
native solver, before any LLM response is collected.

## Admission and measurement

Preserve native turns, legal offers/menus/responses, independent private types,
irreversible commitments and active history-aware partners. Consider positions
with two remaining ego proposal turns and at most four proposal turns overall.
As in the baseline, measure at most two actual ego decisions; an intervening ego
response is a decision and is never skipped.

For each terminal-utility-optimal first action, enumerate branches up to the next
ego decision. At the same resulting physical state and public history, compute
reference actions with (a) the updated semantic judgment and (b) the frozen root
judgment. Evaluate both under the updated support. Give the frozen planner the
best actual outcome among **all** its tied optimal actions. Admit a position only
if the branch-weighted updated-planning advantage is strictly positive. Reject
certificates with undefined counterfactual histories or exhausted exact search;
do not approximate labels or use model errors as selection criteria.

The reference first-action tie rule prefers the first certifiable native menu,
then another certifiable action, among terminal-utility maximizers. It does not
maximize information gain. Every other terminal-optimal action still receives
zero regret. Root action values need not differ: continuation dependence can
exist even when several first actions attain the same optimal utility.

The primary B/P and B→P case is the certified continuation witness with greatest
branch-weighted strict gain. The active J table still enumerates and weights all
branches of the model and reference first actions. P always receives the matching
public history. B→P replaces only the explicit judgment in fresh paired contexts;
history allows re-inference, so this is judgment assistance, not architectural
isolation of B. A positive admission certificate guarantees an opportunity, not
an LLM error or positive repair effect. An action-dependent information difference
must still be read separately from utility differences caused by commitments.
This supplement alone does not establish pure information mediation.

## Run

On the same remote environment as the baseline:

```bash
bash examples/benac_p/run_dependency_diagnose.sh
```

This selects three independent source games per discovery/confirmation split,
then runs the existing preflight and four diagnostic blocks. It reuses the
vLLM/Hermes configuration and balanced reasoning with 1024 completion tokens plus
one 128-token finalization only after truncation. It writes a separate output
directory. Insufficient selection stops before model requests; inspect
`readiness.json` and `selection.json`. The default 64-source-game budget is a
search budget, not a guarantee of six certified games. Override it with
`--candidate-seeds N` in a fresh output directory if necessary. `--export-only`
performs selection without inference. A saved complete `fixtures.json` can be
reused with `--fixtures PATH` in a fresh output directory.

## Validated native example and present status

`examples/benac_p/fixtures/dependency_validation.json` contains one genuine
generated position, `native-40011-g6-d1`. Ego offers a menu to P1; subsequent active
P2 behavior supplies evidence about P2's preference. On a branch of weight 1/3,
the updated judgment is WANT. Its best continuation yields utility 5; every
frozen-judgment-optimal action yields actual utility 4. The expected strict update
gain is 1/3. The root actions tie, so this example does not require the model to
choose that particular menu. Branch weights represent hidden-type uncertainty,
not a stochastic oracle action policy.

The CPU oracle substitution check completed 15/15 tasks with correct judgments,
zero action regret and all four J cells equal to 13/3. This validates measurement
plumbing; it is **not a model result**. Only this one positive fixture has been
validated locally; the six-game research cohort has not yet been filled.

```bash
PYTHONPATH=third_party/negotiation_benchmark/src python -m benac_p.endgame_diagnose \
  --dependency-only --fixtures examples/benac_p/fixtures/dependency_validation.json \
  --min-games-per-condition 1 --oracle-check \
  --output-dir /tmp/benac-dependency-check
```

Oracle-check mode intentionally permits incomplete selection for engineering
validation. Normal inference does not. Report the supplement separately from the
original 36-position results; selected diagnostic opportunities are not estimates
of random-game failure prevalence.

For actual reasoning examples, length statistics and interpretation, see
[the reasoning audit](../runs/benac_native_endgame/full-history-role-context/REASONING_AUDIT.md).
