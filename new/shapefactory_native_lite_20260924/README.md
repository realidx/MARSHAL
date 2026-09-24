# ShapeFactory native Lite: Q0 and old B/P

The archive contains unmodified native CollabSim results and service logs from the Q0 baseline (`876625`), the old B/P run interrupted after 32K context overflow (`876626`), and the old B/P rerun with a 96K context (`876629`). Triton caches are excluded.

| Run | Context | Job exit | Fulfilled agent orders | Both agents fulfilled in a game |
| --- | ---: | ---: | ---: | ---: |
| Q0 `876625` | 32K | 0 | 2/8 | 0/4 |
| Old B/P `876626` | 32K | 1, canceled after overflow | Incomplete run | Incomplete run |
| Old B/P `876629` | 96K | 0 | 5/8 | 1/4 |

The source code for the native Lite runner is the accompanying repository commit. The 96K rerun used `VLLM_BATCH_INVARIANT=1`, `max_num_seqs=32`, one H100-47 GPU, and prefix caching on with chunked prefill off. All four 96K game processes exited zero. Their native `run_summary.complete` flags are false, so the order-fulfillment counts above are reported directly rather than silently equating process exit with game completion. One 96K probe request timed out; there was no 96K context-window error.

These small, non-identical agent trajectories are descriptive evidence, not a controlled estimate of a model treatment effect.

Archive SHA256: `8fc99b1272bd308922f4b08dff5886292b3b9e5df53f6335c91a871bff833c99`.
