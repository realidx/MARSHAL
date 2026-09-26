# Same-checkpoint BENAC: 2/3/4-player results

Six models, three team sizes, 16 frozen games per model/size: 18 complete evaluation runs and 288 attempted games. Each seat uses the same checkpoint with independent private observations/history. All runs have completion markers and successful process exit. O-99's three-player run reached terminal in 15/16 games; one game ended with `invalid_action`. All other runs reached terminal in 16/16. Reaching terminal is not equivalent to successful cooperation.

The archive contains raw per-game `calls.jsonl` and result files, top-level results and summaries, protocols, service logs, serving profiles and completion markers. Two/four-player runs share a service with a later bounded-reference condition; the shared service logs and chain profiles are retained, but `bounded2` result directories are deliberately excluded from this package. Failed/1024-token earlier runs are also excluded.

## Protocol and source

Three-player run source: `fff8232cd16708cb07e8f97459afb704d68f013b`. Two/four-player run source: `ed9b8e564ea38b5136a7bd62a6776174807a694f`. These preserve the `jsonschema.ValidationError` reporting fix and 4096-token budget. No game rules, reward or frozen resets were changed by those fixes.

All: H100-47, BF16, TP=1, vLLM 0.28.0, `VLLM_BATCH_INVARIANT=1`, temperature 0, one rollout per instance, output limit 4096, prefix caching enabled, chunked prefill disabled, cascade attention disabled, eager mode, max model length 32768, max_num_seqs 32. Game concurrency was 4 for two/three-player runs and 1 for four-player runs. Archived launchers are the current combined launcher and its chain wrapper; exact original configuration is recorded in each run's serving profile and protocol.

## Mean team utility

The metric is the sum of player utilities per game, averaged over games. Compare models within a size only: size suites are not equal-difficulty paired tasks and their team utility sums have different numbers of players.

| Model | 2 players /16 games | 3 players /16 games | 4 players /16 games |
|---|---:|---:|---:|
| Q0 | 0.968750 | 0.583333 | 1.177083 |
| Old BP-99 | 1.375000 | 1.437500 | 1.583333 |
| SP-41 | 1.062500 | 0.541667 | 1.250000 |
| O-99 | 1.437500 | [0.911458, 1.067708] | 2.135417 |
| D-39 | 1.281250 | 1.114583 | 1.593750 |
| micro24-39 | 1.062500 | 0.864583 | 1.135417 |

O-99's three-player interval is the full-cohort conservative bound, not a confidence interval. Its completed-only mean is 0.938889 over 15 games. Incomplete games are not imputed as zero. Each summary also reports binary/linear splits, per-player utilities, invalid calls and truncation; nonzero failure counts must not be hidden by terminal completion. These are small fixed-suite descriptive comparisons, not significance claims. Seen/unseen audit labels describe overlap with the audited bank union, not per-model ID/OOD guarantees.

## Jobs and model identity

| Model | 3-player job | 2/4-player chain job |
|---|---:|---:|
| Q0 | 882199 | 882433 |
| Old BP-99 | 882201 | 882437 |
| SP-41 | 882200 | 882432 |
| O-99 | 882204 | 882436 |
| D-39 | 882203 | 882435 |
| micro24-39 | 882202 | 882434 |

D-39 is `decomposed-step39`, distinct from `micro24-step39`; exact export paths are in serving profiles. The recorded checkpoint identities are SHA256 hashes of sorted per-shard SHA256 listings, reused for the same exports across these runs.

Archive: `raw_runs.tar.gz`, checksum in `SHA256SUMS`. Extract into a scratch directory, not over a live checkout; original relative `runs/...` paths are preserved.
