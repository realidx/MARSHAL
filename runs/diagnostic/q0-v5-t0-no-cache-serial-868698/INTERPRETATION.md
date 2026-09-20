# Qwen diagnostic v5: deterministic no-cache rerun

This run completed all 96/96 planned structure replicas and all 408 model
requests with `EXIT_CODE=0`. The server used `--max-num-seqs 1`,
`--generation-config vllm`, `--no-enable-prefix-caching`, and
`--no-enable-chunked-prefill`. The runner used temperature 0, concurrency 1,
three replicas, and a 4096-token limit.

## Determinism gate

The three replicas produced no case-level disagreements in the B judgment,
correct-B planner action, model-B planner action, or end-to-end planner action.
For all nine rows where model B exactly equaled gold B, the two planner calls
also selected identical actions and produced zero repair difference. This run
therefore passes the paired-intervention determinism gate that the earlier
serial run failed.

## Main result

The structure-level results are:

- B exact: 0.09375
- B set exact: 0.4375
- gold-B planning regret: 1.2572916667
- model-B planning regret: 1.215625
- end-to-end P regret: 1.1133069829
- B repair gain: -0.0416666667
- qualitative partner-plan exact gain: 0.0

Supplying gold B did not improve the base model planner under this paired
intervention. The result indicates that incorrect B is not the sole bottleneck:
the model also fails to reliably convert correct partner beliefs into better
actions. There were three stable format failures in each conditional planner
cell; all 96 end-to-end planner calls were valid.
