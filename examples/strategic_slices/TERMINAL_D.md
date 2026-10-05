# Terminal candidate D evaluation on SoC

The real Qwen3-4B-Instruct-2507 evaluation completed on SoC on 2026-10-05:
**800 candidates from 100 parents, eight independent trajectories each**.
Original job 910916 supplied 58 completed parents; 32-worker completion-refill
job 911072 reused them and finished the other 42. Full evidence is in
[`new/strategic_slices_terminal_d_20261005`](../../new/strategic_slices_terminal_d_20261005/README.md).
It does not train weights or select the final 100 slices.

Local validation completed: 22 tests; full 6,400-trajectory CPU mock and independent
native replay; complete-run resume without further generation; standalone archive
checksum and offline-entry checks. Mock uses a legal random actor, not Qwen.
The full mock used the earlier 4-worker/1,024-output-token profile. The current
user-requested profile uses 32 workers, completion-driven refill, and 4,096 output tokens; local regression
and configuration checks cover this update, without a real GPU run.

## Runtime configuration

Defaults are in `terminal_d_soc.json`. The historical sources are the SoC B/P
probe launcher and the recorded job 846913 review; they are local evidence of
past working configurations, not confirmation that those remote paths still exist.

| Setting | Value |
| --- | --- |
| Model | `/home/e/e1300530/models/Qwen3-4B-Instruct-2507` |
| Python | `/home/e/e1300530/tmp/marshal-vllm09/bin/python` |
| Slurm | `gpu`, `gpu:h100-47:1`, 8 CPUs, 64 GB RAM, 3-hour limit |
| vLLM | BF16, TP=1, Hermes parser, localhost port 18083 |
| Concurrency / GPU memory fraction | 32 / 0.40 |
| Sampling | temperature 0.8, top_p 1, top_k -1, repetition_penalty 1 |
| Context / output budget | 16,384 / 4,096 tokens |
| Repeats / seed | 8 / 42 |

Job 846913 recorded vLLM 0.28.0, Transformers 5.16.1 and Torch 2.13.0.
The launcher records actual versions and hashes the local model weights,
tokenizer and configuration. It installs nothing. Context 16,384 follows the
small-probe profile; the earlier pilot used 5,120. The three-hour walltime and
64 GB CPU RAM are the allocation settings; continuation job 911072 completed in 27m55s.
At most **11,128 model calls** are possible (6,400 trajectories times their k);
early terminal branches can use fewer. The GPU visibility assigned by Slurm is
preserved, including MIG UUIDs. The launcher stops only its own server group.

## Sampling and D

For each candidate, independently draw eight `(entrance, hidden world)` pairs
from its saved joint distribution. A singleton has a fixed entrance; four
collective controls contain multiple correlated entrances/worlds. Each replica
uses separate seeded streams for reset, model outputs and reference actions.
There are no two-by-four groups and no per-world quotas.

The model receives its own preferences, visible public history/state, its own
private answers, public preference support/prior, legal native `act` actions,
and the remaining control window. It never receives hidden preferences, exact
world identity, oracle Q values, optimal actions or teacher certificates.
The model controls at most k focal decisions (including responses). Partners,
and focal decisions after k, use the same saved initial terminal profile. The
runtime restores the native tree and saved policy, without calling the solver.
It checks every dynamic tool-augmented prompt against the context limit and
checks server prompt-token counts; no input truncation is permitted.

For eight completed trajectories:

`D = V_star - mean(terminal utility)`; also report `D / C`.

Negative Monte Carlo estimates are retained. Per-slice standard errors and
bootstrap intervals are descriptive with only eight observations. Invalid
actions and output truncation are recorded as model failures, with null terminal
utility. If any replica fails, primary D is null; completed-only estimates are
explicitly named and conservative missing-outcome bounds are also reported.
Infrastructure/transport failures abort rather than becoming game rewards.
No failed answer is automatically retried or replaced with an oracle answer.

## Training signal diagnostics

Report reward spread, completion/format/truncation rates, distinct model action
trajectories, and first-action oracle-value contrasts within identical visible
prompts. The latter compares the chosen first action using the saved `root_Q`
and optimal continuation within the remaining k window; it is not the model's
complete-trajectory quality, especially for k>1.

Raw reward variation can come from the hidden world and reference randomness.
It is **not** reported as a GRPO active-group rate: replicas have independent
resets. Root-value contrast is a useful additional diagnostic, not proof of
learnability or reasoning correctness. Even eight identical results do not
establish that a slice cannot provide a learning signal.

All splits are measured as requested (train 504, validation 96, test 200).
Reports keep them separate. `train_signal_candidates.jsonl` contains only train
slices with all eight completed trajectories and an observed root-value contrast;
it is a diagnostic list, not the final training selection. The summary reports
whether at least 100 such train candidates were observed. Test results must not
drive training-slice selection; this base-model diagnostic consumes a test look.

## Local checks and packaging

Use a Python environment with NumPy and SciPy; GPU libraries are only imported
by the actual allocation launcher. From the repository root:

```bash
python -m examples.strategic_slices.run_terminal_d --check
python -m unittest training.strategic_slices.test_terminal_d -v
python -m training.strategic_slices.terminal_d --mock \
  --output new/local_data/terminal_d_mock --limit-parents 2
```

Omit `--limit-parents` for a full CPU mock of all 6,400 trajectories. Mock reports
are labeled throughout and do not provide model D or training-signal evidence.

The unpacked candidate dataset lives under ignored `new/local_data`. The standalone
archive and its checksum sidecar are stored at Git-trackable paths:
`examples/strategic_slices/strategic-slices-terminal-D.tar.gz` and
`examples/strategic_slices/strategic-slices-terminal-D.tar.gz.json`.
Commit both files to transfer the packaged data through Git. The archive contains
the current Python sources, launchers, configuration, candidate data and reference
evidence. Its generation command is:

```bash
python -m examples.strategic_slices.prepare_terminal_d_bundle \
  --output examples/strategic_slices/strategic-slices-terminal-D.tar.gz
```

The script defaults to that path and refuses to overwrite an existing archive;
use a fresh `--output` path when rebuilding for review. After committing/pulling
the archive or transferring it yourself, extract into a **new directory** on SoC. Its
adjacent JSON records the archive SHA-256. `TERMINAL_D_BUNDLE.json` inside the
archive lists every included file hash. No model weights are included. For a
standalone extracted bundle, inspect/check checksums from that directory:

```bash
SLICES_D_PYTHON=/home/e/e1300530/tmp/marshal-vllm09/bin/python \
  bash examples/strategic_slices/run_terminal_d.sh --check
```

`--check` never launches vLLM or submits a job; it validates the candidate pool
and prints resolved settings. Model/GPU paths and actual versions are checked
only inside the allocation.

## Manual execution only

After transferring and checking the bundle, the user can submit from its root:

```bash
sbatch examples/strategic_slices/sbatch_terminal_d.sh \
  --output /home/e/e1300530/tmp/strategic-slices-D-qwen3-4b-r8
```

This command is documentation only; the pipeline never invokes `sbatch` itself.
Overrides: `SLICES_D_PYTHON` for Python, `--model`, `--data`, `--port`, or a complete
`--config` JSON. Use a fresh output directory for a different protocol.

Each parent is committed atomically after its 64 trajectories. On interruption,
resubmit manually with the **same settings and output path**, adding `--resume`.
Completed parents are reused; only an unfinished parent is replayed, with the
same seeds. Its previous partial HTTP evidence remains in the old attempt
directory and is not counted twice. Model/data/source/version changes reject
resume. A completed run resumes without further model calls.

## Outputs

- `attempt-*/runtime.json`, `server.log`, `transport.jsonl`: actual environment,
  model/launcher hashes, raw model requests/responses and transport failures.
- `evaluation/protocol.json` and `source/`: exact evaluation/source identity.
- `evaluation/parents/*.json`: checksummed trajectories, reset indices, reference
  actions, model calls and per-slice metrics; sufficient for local inspection.
- `evaluation/slices.jsonl`, `summary.json`, `REPORT.md`: D, uncertainty, failure
  and signal metrics, separated by split and stratified by k/player count/kind.
- `evaluation/train_signal_candidates.jsonl`: train-only diagnostic candidates.
- `evaluation/COMPLETE.json`: output hashes, not a learning-success certificate.
  `FAILED.json` records interrupted evaluations; successful recovery moves it to
  `RECOVERED_FAILURE.json`.

## SoC completion-refill continuation (2026-10-05)

The optimized launcher uses `workers=32` and
`scheduler=completion-refill-v1`. Each completed HTTP request immediately frees
a slot for another ready trajectory; at most one call per trajectory is in
flight. Parent records remain atomic and independently seeded. The tokenizer
is protected against concurrent state mutation.

The original 16-worker job 910916 was cancelled only after CPU checks and
legacy-result validation passed. Its 58 complete parents (3712 trajectories)
were copied byte-for-byte to the continuation, with original protocol hashes
retained. Job 911072 continues the other 42 parents. Model, sampling settings,
4096-token cap, reset streams, and scoring are unchanged; batch scheduling can
change numerical generations. `EXECUTION_MIGRATION.json` records both identities
and all inherited parent hashes. Inherited and new parents form a mixed execution
measurement, not a token-identical rerun.

`migrate_terminal_d_execution.py --old OLD_EVALUATION --new NEW_EVALUATION`
validates without modifying either output; add `--apply` to create a new
continuation directory. It permits only the recorded 16-to-32/refill change
and terminal_d scheduler source change, preserving model/data/prompt sources,
all other configuration, and full replica coverage. Never modify a live run's
source or output to migrate. Submit the new directory using `--resume`.

Validation: eight original CPU tests, two refill/trajectory/recovery tests,
and the HTTP context/transport regression passed in Python 3.10. The refill
test blocks one request and verifies that a later request starts before that
request is released; the recovery test forbids any new generation for a copied
complete parent. Continuation job 911072 completed successfully in 27m55s. The full results
and original/continuation evidence are archived in
[`new/strategic_slices_terminal_d_20261005`](../../new/strategic_slices_terminal_d_20261005/README.md).
