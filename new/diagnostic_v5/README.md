# Native-semantic B/P diagnostic

This is the replacement for the numeric v4 diagnostic.  The model-facing
interface is now the same qualitative contract used by the game agent:

- B calls `SUBMIT_BELIEFS` with `possible_preferences` and `favored`;
- controlled P receives exactly those two fields;
- no posterior, probability vector, joint distribution, or per-world payoff is
  included in a model request;
- the exact teacher posterior remains backend-only for action regret.

## Suite

The suite contains 16 independent structures (eight binary and eight linear),
each with matched voluntary and preset histories.  A pair has the same current
physical state, legal actions, per-world payoff table, and fixed continuation
policy.  Its native semantic B labels differ and its exact reference-optimal
action sets are disjoint.  One v4 structure whose posterior changed without
changing `possible_preferences/favored` was removed and replaced before any v5
model run.

Each case runs:

1. native semantic B from the visible history;
2. P with the model's semantic B output;
3. P with the correct semantic B output;
4. native end-to-end history-to-action P.

Eight voluntary cases also repeat B with qualitative partner-plan assistance.
The assistance reports only an ordering such as impossible/most likely/least
likely, never likelihood or posterior numbers.

## Interpretation

The local teacher uses its exact posterior only to score the selected action.
`P_gap_given_correct_B` therefore diagnoses planning despite a correct native
judgment.  `B_repair_gain` is the paired utility change from replacing the
explicit model judgment with the correct judgment while keeping the same
planner, history, state, tools, and sampling seed.

There is deliberately no `model_B_reference_P` cell.  A semantic judgment does
not identify a unique numerical posterior, so optimizing a reference planner
under a made-up model distribution would recreate the v4 mismatch.  The v5
experiment consequently reports semantic B accuracy, correct-B P regret,
model-B composition regret, end-to-end regret, and paired B-repair effects—not
the old numeric four-cell decomposition or TV error.

The public history remains visible in controlled P, matching the deployed
agent context.  Thus B replacement measures judgment assistance, not an
isolated internal neural module: the planner may also reason from history.

## Run

```bash
python new/diagnostic_v5/experiment.py \
  --base-url http://127.0.0.1:8000/v1 \
  --model YOUR_SERVED_MODEL \
  --output runs/diagnostic/YOUR_RUN/structure_v5 \
  --repeats 3 \
  --max-tokens 4096
```

CPU checks:

```bash
python -m unittest discover -s new/diagnostic_v5 -p 'test_*.py' -v
```
