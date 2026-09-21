# Old and new BP-99 checkpoint results

This index binds the two BP-99 HF exports to their complete frozen evaluation artifacts. Model weights are intentionally not stored in Git; their SHA256 hashes and export metadata are included under `exports/`.

| Checkpoint | HF export path at evaluation time | `model.safetensors` SHA256 |
|---|---|---|
| old BP-99, training job 860494 | `/home/e/e1300530/tmp/hf-exports-860494/bp-step99` | `aab6fdb53542132f3818909f533678b5d01d31ce984e53674ebf90e14b737ab9` |
| new BP-99, training job 866677 | `/home/e/e1300530/tmp/hf-exports-866677/bp99-866677` | `da1e2d41b3b041b64cf67a9961f6b9cab4e0338f490b6f2fb7747110070515d3` |

## Frozen CalBench

The authoritative batch-invariant runs are:

- old BP-99: `runs/calbench_soc/old-bp99-860494-biinv-v1-stream-868934/`
- new BP-99: `runs/calbench_soc/new-bp99-866677-biinv-v1-stream-868933/`

Both used the frozen deterministic serving profile (`VLLM_BATCH_INVARIANT=1`, temperature zero, TP=1, eager mode, `max_num_seqs=32`, prefix caching enabled, chunked prefill and cascade attention disabled). Each directory includes all 24 game traces, per-agent transport logs, scenarios, execution identity, runtime environment, routes, and completion manifest.

| Model | Coordinated success | Successful and optimal | Completion score | Headline score |
|---|---:|---:|---:|---:|
| old BP-99 | 10/24 | 8/24 | 0.611 | 0.593364 |
| new BP-99 | 5/24 | 5/24 | 0.500 | 0.478781 |

## Diagnostic results

The full raw diagnostic results are stored in the following tracked directories:

- frozen diagnostic v5:
  - `runs/diagnostic/old-bp99-860494-v5-biinv-v1-868939/`
  - `runs/diagnostic/new-bp99-866677-v5-biinv-v1-868938/`
- initial clean-state diagnostic v6:
  - `runs/diagnostic/old-bp99-v6-biinv-v1-870264/`
  - `runs/diagnostic/new-bp99-v6-biinv-v1-870265/`
- authoritative strengthened, decision-sufficient diagnostic v6:
  - `runs/diagnostic/old-bp99-v6s-biinv-v1-870332/`
  - `runs/diagnostic/new-bp99-v6s-biinv-v1-870333/`

The strengthened-v6 comparison and exact submission script are documented in `runs/diagnostic/v6s-bp99-comparison-20260921/README.md`.

The older v5 and initial-v6 outputs are retained as methodological history. Use strengthened v6 for the causal B-to-planning claim because it restricts evaluation to semantic-B regions proven decision-sufficient and reports paired scoring on identical valid rows and structure weights.
