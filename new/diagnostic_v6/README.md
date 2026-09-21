# Decision-sufficient native-semantic B/P diagnostic

This suite fixes a confound in v5.  The v5 controlled-P request supplied a
semantic B judgment but also retained the behavioral chronology, so the model
could bypass that judgment by reconstructing B from the original evidence.

v6 separates the interfaces:

- B receives the full voluntary or preset history;
- controlled P receives the current decision state and either model B or gold
  B, but no behavioral chronology or provenance metadata;
- end-to-end P retains the native history and receives no explicit judgment;
- exact posteriors and per-world payoffs remain backend-only.

The suite keeps only matched structures for which the native semantic B is
decision-sufficient. For each case, exact rational vertex enumeration covers
the complete closed posterior region compatible with
`possible_preferences`/`favored`; every vertex has the same exact
optimal-action set. Affinity of action value in the posterior then proves the
set is invariant throughout the region. The invariant sets for the voluntary
and preset cases are disjoint. The closed-region check is conservative at
strict support and favored-margin boundaries.

The controlled-P state retains the game, goal requirements, public and own
preferences, current commitments, remaining turns, investigation quota, legal
actions, and fixed partner policy.  Within every matched structure, the
voluntary and preset controlled-P base requests and tools are byte-identical.
Only the inserted `possible_preferences` and `favored` fields may differ.

## Run

Start vLLM with batch invariance enabled, then run:

```bash
VLLM_BATCH_INVARIANT=1 vllm serve YOUR_MODEL ...

python new/diagnostic_v6/experiment.py \
  --base-url http://127.0.0.1:8000/v1 \
  --model YOUR_MODEL \
  --output runs/diagnostic/YOUR_RUN/structure_v6 \
  --repeats 3 \
  --temperature 0 \
  --max-tokens 4096 \
  --checkpoint-hash YOUR_CHECKPOINT_HASH
```

The server may retain chunked prefill and production concurrency after the
same-request repetition check passes under `VLLM_BATCH_INVARIANT=1`.

`summary.json` contains a `paired_scoring_identity` block.  Its two regrets
and repair gain use exactly the same valid rows and structure weights, and the
runner reports both row-level and aggregate identity residuals.  The ordinary
condition-specific means may have different valid subsets and must not be
subtracted to reconstruct repair.

Here “correct B” means the correct deployed semantic summary
(`possible_preferences` and `favored`), not a complete posterior.  The suite
therefore measures action selection after the actual agent interface. Because
every retained summary is certified decision-sufficient, a controlled-P error
cannot be attributed to missing posterior magnitudes.

CPU checks:

```bash
python new/diagnostic_v6/build.py
python -m unittest discover -s new/diagnostic_v6 -p 'test_*.py' -v
```
