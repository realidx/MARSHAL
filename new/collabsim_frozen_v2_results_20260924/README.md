# CollabSim frozen v2 runs (2026-09-24)

This archive preserves native outputs, traces, events, probes, generated configs,
serving profiles, and the Slurm wrapper used for Q0, old B/P-99, SP-41, and O-99.
The source commit was `18987710970592f73c6423eb1e5243b7e2916df3`.
All model services used vLLM 0.28.0, BF16, TP=1, `VLLM_BATCH_INVARIANT=1`,
`max_model_len=98304`, `max_num_seqs=32`, prefix caching on, chunked prefill off,
and eager mode. Each run's `SERVING_PROFILE.txt` records its model and checkpoint
identity label. These labels are operator-supplied, not remote weight verification.

The intended v2 task has four three-person ShapeFactory conditions and three
repeats of the *same* Hidden Profile case. At the user's request, redundant
Hidden Profile repeats were stopped and subsequent runs used `v2single` (one
repeat). `v2single` is a reduced-repeat variant, not the original seven-run
frozen suite. Q0's first Hidden Profile repeat was complete before its job was
cancelled; its incomplete second repeat is retained but excluded below.

| Model | ShapeFactory sources used | Fulfilled order items | All-three fulfilled games | Hidden Profile source |
| --- | --- | ---: | ---: | --- |
| Q0 | `q0-v2-877899` | 1/12 | 0/4 | `q0-v2-877899`, repeat 00 |
| old B/P-99 | first three conditions: `oldbp99-v2-877961`; reverse-dashboard: `oldbp99-v2missing-878073` | 1/12 | 0/4 | `oldbp99-v2missing-878073`, repeat 00 |
| SP-41 | `sp41-v2single-877996` | 2/12 | 0/4 | `sp41-v2single-877996`, repeat 00 |
| O-99 | `o99-v2single-877997` | 2/12 | 0/4 | `o99-v2single-877997`, repeat 00 |

Each counted ShapeFactory process exited zero and produced a native summary;
none of the four models completed all three orders in any game. Each counted
Hidden Profile process also exited zero, but **none produced an initial or final
vote**. All four runs reached the final phase and stopped after the 30-step
limit (`steps_taken=31`); their validated actions contained messages and/or
`do_nothing`, but no `decide`. Therefore native metric values of zero for vote
accuracy are **missing decisions**, not observed incorrect votes. This single
case/repeat does not provide independent-case accuracy or a reliable ranking.

The other directories are retained for provenance, not included in the table:

- `oldbp99-v2single-877995` stopped in forward-dashboard when accumulated
  prompt history exceeded 98,304 tokens (HTTP 400); this is an infrastructure
  validity failure, not a model decision. Its forward-private result is excluded.
- `sp41-v2-877962` and `o99-v2-877902` are cancelled partial attempts.
- `oldbp99-v2-877961` was cancelled during reverse-dashboard, after three
  conditions had exited zero. Mixing those three conditions with a later job
  is explicit; it is not one continuous, fully paired run.

The wrapper under `runner/` was kept outside the repository during execution
to preserve the clean-checkout guard. Its `v2missing` mode checks the three
old B/P source exit codes and reruns only reverse-dashboard plus one Hidden
Profile repetition. Do not infer task success from `EXIT_CODE=0`, `COMPLETE`, or
native process exit codes; use each game's `run_summary.json` and the error logs.
