# Unified structure-level B/P diagnostic

This directory replaces the separate development component panel and the
single-structure v3 repair pilot with one frozen diagnostic suite.  It does not
modify v2/v3 or any training data.

## What one structure contains

Each of the 16 independent structures has a voluntary and a preset case.  The
two cases end at the same physical state with the same legal actions, certified
per-world payoff table, and fixed continuation policy.  Only the evidential
status of the preceding behavior differs.

For every case the runner obtains:

1. `B`: a numeric posterior from the native visible history;
2. `correct_B_model_P`: model planning with the certified posterior;
3. `model_B_model_P`: model planning with its own posterior;
4. `end_to_end_P`: the native unassisted history-to-action decision;
5. two offline reference-P cells, under the model and certified beliefs.

Eight voluntary cases additionally run `B_with_planning_assistance`.  The only
extra input is the native teacher's likelihood of the observed partner action
under want/neutral/avoid.  This embeds the old P-to-B component question in the
same native structure: improvement localizes a failure in modeling the
partner's plan, while persistent error localizes the remaining Bayesian update
or grounding failure.  It is not a claim about internal causal modules.

## Frozen suite

- 16 canonical geometries: 8 binary and 8 linear;
- 32 matched cases and three default replicas;
- 408 maximum model calls per model;
- every structure is disjoint, up to exact player/commitment/goal renaming,
  from active v6 train, validation, and test data, BENAC-A final evaluation,
  and the v3 development pilot;
- selection uses teacher quantities only and was frozen before model calls;
- evidence TV is at least 0.15, voluntary/preset exact optimal action sets are
  disjoint, and both decision gaps are at least 0.15.

The selected behavioral evidence is not label-balanced: most voluntary
posteriors favor `avoid`.  The matched preset half remains uniform, and scoring
uses the full numeric distribution rather than a favored-class accuracy.  This
limitation must be disclosed; the suite should not be presented as a general
posterior calibration benchmark.

`cases.json`, `certificates.json`, and `selection.json` are frozen by
`manifest.json`.  `build.py` deterministically regenerates them, but should not
be rerun after any model has been evaluated if the results are to retain frozen
test status.

## Metrics

All utilities are evaluated under the certified posterior, even when a cell is
given the model posterior.  The primary structure-weighted metrics are:

- `B_total_variation`;
- planning regret under the certified belief;
- planning regret under the model's own belief;
- native end-to-end planning regret;
- the four repair-path gains, total gap, and interaction gamma;
- `planning_assistance_TV_gain` on the eight assisted structures.

The four repair gains are two paths through the same four-cell table.  They are
not four additive contributions.  `B_repair_gain`, `P_repair_gain`, and gamma
may be negative.  Invalid or truncated output remains missing and is never
converted to PASS or zero utility.  `summary.json` reports row-, structure-, and
mode-level aggregates plus coverage.

## Run

The runner does not start a model server:

```bash
python new/diagnostic_v4/experiment.py \
  --base-url http://127.0.0.1:8000/v1 \
  --model YOUR_SERVED_MODEL \
  --output runs/diagnostic/YOUR_RUN/structure_v4 \
  --repeats 3 \
  --max-tokens 4096
```

Multiple endpoints may follow `--base-url`.  Keep temperature, top-p,
max-tokens, and replicas identical across Q0/BP/SP.  There are no retries.

CPU regression tests:

```bash
python -m unittest discover -s new/diagnostic_v4 -p 'test_*.py' -v
```

The current v3 `binary_complementarity` example remains a useful worked
development example but is not part of these 16 structures.
