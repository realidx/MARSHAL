# Clean-state native-semantic B/P diagnostic

This suite fixes a confound in v5.  The v5 controlled-P request supplied a
semantic B judgment but also retained the behavioral chronology, so the model
could bypass that judgment by reconstructing B from the original evidence.

v6 separates the interfaces:

- B receives the full voluntary or preset history;
- controlled P receives the current decision state and either model B or gold
  B, but no behavioral chronology or provenance metadata;
- end-to-end P retains the native history and receives no explicit judgment;
- exact posteriors and per-world payoffs remain backend-only.

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
  --max-tokens 4096
```

The server may retain chunked prefill and production concurrency after the
same-request repetition check passes under `VLLM_BATCH_INVARIANT=1`.

CPU checks:

```bash
python new/diagnostic_v6/build.py
python -m unittest discover -s new/diagnostic_v6 -p 'test_*.py' -v
```
