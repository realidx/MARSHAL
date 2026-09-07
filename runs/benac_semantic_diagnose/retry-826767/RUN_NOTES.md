# BENAC-P semantic diagnosis: job 826767

This directory records the completed remote run before the follow-up prompt
change. It is intended to make local diagnosis reproducible without contacting
the inference server.

## Run provenance

- Command: `bash examples/benac_p/run_full_diagnose.sh`
- Scheduler job: `826767`
- GPU: `H100-47` (`xgpi20`)
- vLLM: `0.28.0`
- Tool-call parser: `hermes`
- Model: `Qwen/Qwen3-4B-Instruct-2507`
- Model endpoint: `http://localhost:8000/v1`
- Semantic-suite version: `semantic-interaction-loop-v1`
- Protocol version: `brief-reasoning-tools-v2`
- Bundles/games: `12 / 36` (6 discovery, 6 confirmation)
- Seed: `20000`
- Workers: `4`
- Completion cap: `1024` tokens

## Protocol telemetry

- Total task slots: `600`
- Completed model requests: `584`
- Tool-call completions: `479`
- Length-truncated requests: `105`
- Blocked by failed parent: `16`
- Invalid parsed responses: `0`
- Mean completion length: `493.93` tokens
- P95 completion length: `1024` tokens
- Mean reasoning length: `365.91` whitespace-delimited words
- P95 reasoning length: `809` words
- Reasoning present in all `584` attempted model responses

## Measurement quality

The main `confirmation / unknown_relevant` condition has format-valid coverage
of `93/126` and `0/6` complete games. The `known` control has `55/66` valid
requests and `1/6` complete games; `unknown_irrelevant` has `99/111` valid
requests and `0/6` complete games. These are pilot diagnostics only, not a
confirmation claim.

The raw reasoning in `answers.json` shows repeated route/menu enumeration in
length-truncated responses. The stored `report.md`, `summary.json`,
`protocol_summary.json`, `scores.json`, `rollouts.json`, task exports, oracle
labels, certificates, and interventions provide the corresponding analysis
inputs.

The follow-up source change adds an explicit semantic-suite instruction of at
most two short sentences and 80 words, plus a ban on exhaustive enumeration.
This artifact remains an immutable record of the original v2-prompt run; it
is not rewritten to appear as if it used the follow-up prompt.
