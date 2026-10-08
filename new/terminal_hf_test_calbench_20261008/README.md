# Qwen3-4B-Instruct terminal training, test and CalBench evidence

Model: Qwen3-4B-Instruct-2507. Branch: game-slice. Full training job 915731 used one H100-96, a 24-hour allocation, 32 rollout trajectories per update and a 6M response-token target. It was deliberately paused after 550 updates / 3,500,783 response tokens; it is **not a completed 6M-token training run**. Retained native checkpoints: best `checkpoint-379` (380 updates), latest `checkpoint-549` (550 updates). Both exported models were tested on the same frozen terminal test and all 24 CalBench stream cases.

## Read first

- `RUNS.json`: actual jobs, parallelism, budgets and execution settings.
- `summary.json`: terminal and all-24-case CalBench results. The 16-case s2/s3 subset is auxiliary only.
- `audit/README.md`: test coverage, paired differences, per-k results and integrity checks.
- `audit/replay.json`: original Validator replay of 4,349 best and 4,418 latest saved requests; all scores and trajectories match.
- `scheduler_logs/`: original Slurm output for full training and both paired evaluations.
- `*-EXPORT_VERIFIED.json` and `raw/export-logs.tar.gz`: model export identities, verification and logs.

## Original files

Everything in `raw/` is losslessly archived, without rewriting JSON, requests, responses or traces. `raw/MANIFEST.json` lists each original file, its source path, uncompressed size and SHA-256, plus hashes of each archive/part.

| Bundle | Original contents |
|---|---|
| terminal-best / terminal-latest | Full report.json, requests.jsonl (wire requests/responses, exact token/logprob evidence), completion marker, evaluation log, exit code and vLLM server log |
| calbench-best / calbench-latest | All 24 cases, traces, events, transport evidence, result JSON, routes, execution identity and runner log |
| training-915731 | Every non-checkpoint file under the run: training calls, games, update units, validation trajectories, metrics, phase timings, resolved config, environment, source manifest, checkpoint retention and final/pause records |
| frozen-terminal-data | Entire frozen candidate pool and selected training data, including reference trees, provenance and integrity markers |
| calbench-source | Exact restored third_party/calbench source/dependencies used for these evaluations |
| export-logs | Successful CPU export jobs 919151 and 919152 stdout/stderr |

Large archives are split into ordered 32 MiB `.partNNN` files. Verify all original bytes with:

```bash
python new/terminal_hf_test_calbench_20261008/verify_raw.py
```

For split archives, concatenate parts in lexical order before extraction:

```bash
cat raw/training-915731.tar.gz.part* > /tmp/training-915731.tar.gz
tar -xzf /tmp/training-915731.tar.gz -C /your/analysis/directory
```

Frozen terminal data and CalBench source archives have repository-relative paths; extract them from the repository root when reproducing. The original run scripts contain machine-specific model/env paths; adjust these to the available installation. `package_raw.py` records how the evidence was packaged; the two scripts in `audit/` reproduce the replay and root-Q consistency checks from the original local run paths.

## Limits

Test contains 200 slices / 25 parents, repeated 8 times with temperature 0; those 1,600 trajectories are not independent questions. Neither validation nor test contains positive-information entrances, and the test has historical base-model D exposure. Full metrics and local slice correctness answer different questions. CalBench uses temperature 0 / 4096 output tokens; terminal uses temperature 0 / 1024. Native checkpoint tensor/optimizer files (~105 GiB) and HF weight shards (~15 GiB) remain local; their hashes, source checkpoints and export provenance are included. Unrelated earlier tic-tac-toe results are not part of this experiment.
