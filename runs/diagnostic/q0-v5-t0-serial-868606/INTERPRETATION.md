# Qwen diagnostic v5: serial temperature-zero rerun

This run completed all 96/96 planned rows with `EXIT_CODE=0` using:

- one H200 GPU;
- vLLM 0.28.0 with `--max-num-seqs 1`, eager execution, and the vLLM generation config;
- runner concurrency 1;
- temperature 0;
- three replicas; and
- a 4096-token generation limit.

## Important validity caveat

Serial execution did **not** make the paired planner calls deterministic. Among
the eight row instances where the model B judgment exactly equaled gold B, the
`correct_B_model_P` and `model_B_model_P` requests were byte-for-byte equal and
used the same request seed, but three pairs returned different action/status
outcomes. One of those pairs produced a nonzero repair difference
(`B_repair_gain = -0.5`).

Across the 32 cases, the three replicas also disagreed for 7 B judgments, 18
correct-B planner outputs, 21 model-B planner outputs, and 25 end-to-end planner
outputs.

Consequently, the aggregate structure-level `B_repair_gain = -0.001544...`
must not be interpreted as a causal paired-intervention estimate. The B
accuracy and planning-regret measurements remain usable as descriptive results,
with the nondeterminism caveat.
