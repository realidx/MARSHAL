# Q0 CalBench 24-game runs: raw data and comparability

These are the surviving Qwen3-4B-Instruct-2507 (Q0) runs on the same 24
frozen scenario manifest, SHA256
`87211ff5e8bf11eb287a04dfeb44713db0270092366895bd8dd13ba046abd84c`.
All six completed runs used the same model-file hashes and recorded
temperature 0, `max_tokens=4096`, and the
`reasoning-separated-v2-tokens-4096` protocol. They did **not** all use
the same serving/code configuration.

| Archive | Complete success | Meetings | vLLM configuration | Comparability |
| --- | ---: | ---: | --- | --- |
| `runs/r3-6of24-865854.tar.gz` | 6/24 | 41/72 | max_num_seqs=4; prefix cache on; chunked prefill on; batch invariance unset | Early pre-freeze |
| `runs/r4-4of24-868761.tar.gz` | 4/24 | 34/72 | Same early pre-freeze group | Early pre-freeze |
| `runs/fast8-5of24-868896.tar.gz` | 5/24 | 39/72 | max_num_seqs=32; prefix cache on; chunked prefill off; batch invariance unset | Later pre-freeze |
| `runs/fast8-2of24-868916.tar.gz` | 2/24 | 32/72 | Same later pre-freeze group | Later pre-freeze |
| `runs/frozen-5of24-868929.tar.gz` | 5/24 | 37/72 | max_num_seqs=32; prefix cache on; chunked prefill off; cascade attention off; VLLM_BATCH_INVARIANT=1 | Frozen v1 |
| `runs/frozen-5of24-868930.tar.gz` | 5/24 | 37/72 | Same frozen v1 group | Frozen v1 |
| `runs/r2-failed-865843.tar.gz` | No score | — | Startup failed; EXIT_CODE=1 and no game traces | Infrastructure record only |

The two frozen runs have identical success status and meeting count for
each of the 24 cases. Their raw transcripts and metadata are preserved
separately. The older 2/4/6-success observations are real completed runs
on the same scenarios and model, but **must not be pooled as repeated
measurements of the frozen v1 protocol**: server settings and recorded
runner/adapter script identities differ among the three groups.
For direct comparison to the archived frozen D and old B/P results, use
the two `frozen-5of24` runs.

Each completed-run archive contains saved per-game traces and transport logs,
`games/results.json`, `games/frozen_manifest.json`,
`games/execution_protocol.json`, model and script file hashes in
`execution_identity.json`, runtime environment, server configuration,
server logs, and a completion marker. The failed-run archive instead retains
its launch-failure marker and available server/runtime logs. Generated
`triton-0/` compilation caches and model weights are excluded.

Extract with `tar -xzf runs/ARCHIVE.tar.gz -C DESTINATION`. Verify all
archives with `sha256sum -c SHA256SUMS` from this directory.
