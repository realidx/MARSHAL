# SoC: small B/P tools-only probe

This is the next frozen Qwen3-4B-Instruct-2507 diagnostic, using the reviewed
`bp-readable-prompt-v2` prompts. It performs **64 formal requests plus 2 preflight
requests**, with no training or weight updates. There is no text-JSON answer arm.
B calls `SUBMIT_BELIEFS`; P calls `OFFER`, `INVESTIGATE`, `PASS`, `ACCEPT` or
`REJECT` directly, as allowed by the current question. Brief explanation remains
in ordinary message content. Text pretending to be a tool call is not repaired.

## Push and submit

Everything needed on the cluster is inside **`examples/bp_probe_nus/`**, including
the small frozen visible question bundle and standalone sampler. Include this
whole directory in your commit/push. The cluster does not need ignored local
data, `training/b_sft`, teacher labels, scipy, or solver execution.

On SoC, from your checkout of the pushed branch:

```bash
cd /home/e/e1300530/MARSHAL
git pull --ff-only
sbatch examples/bp_probe_nus/sbatch_probe.sh
```

This reuses the previously recorded SoC setup:

- Partition `gpu`, one `gpu:h100-47:1`, 8 CPUs, 1-hour job limit.
- Python `/home/e/e1300530/tmp/marshal-vllm09/bin/python`.
- Model `/home/e/e1300530/models/Qwen3-4B-Instruct-2507`.
- One localhost vLLM service on port 18081, Hermes tool parser, BF16, TP=1.
- Context 16384, output limit 1024, temperature 0.8, two HTTP workers on the
  same GPU, two samples per condition. GPU memory utilization 0.40.

These are historical environment paths, checked when the job starts; no package
installation is attempted. If paths changed, override before submission:

```bash
export BP_PYTHON=/path/to/environment/bin/python
export BP_MODEL=/path/to/Qwen3-4B-Instruct-2507
sbatch examples/bp_probe_nus/sbatch_probe.sh
```

Other overrides: `BP_PORT`, `BP_GPU_MEMORY`, `BP_CONTEXT`, `BP_WORKERS` (1–4),
`BP_RUN_ROOT`. Preserve model/version and sampling settings for this comparison.
The launcher checks actual tokenized inputs with tools against context capacity;
it never truncates questions. It respects Slurm GPU visibility, refuses more
than one visible GPU or an occupied port, and stops only its own server process
group on completion or failure. No pre-existing model service is required.

Offline validation, including from a checkout without local teaching data:

```bash
BP_PYTHON=python3 bash examples/bp_probe_nus/run_probe.sh --check
python3 -m unittest discover -s examples/bp_probe_nus -p 'test_*.py'
```

## Small test composition

There are 24 base questions: 12 B and 12 P. B includes behavior-based exclusion,
correct full-set retention, formation/maintenance/update, favored changes,
private truth, and 3-player cases. P includes complete information, own vs social
payoffs, investigate-now vs deadline, using private answers, and qualitative
likely/unlikely/certain/very-likely assessments.

Four sources additionally have a matched renamed/no-teaching and
renamed/short-teaching pair: B acceptance, B favored maintenance, P investigation
root, and P planning after an avoid answer. Total: **32 conditions**, evenly
split B/P, each sampled twice. This retains a few teaching controls without
repeating the previous full sweep. Two samples cannot estimate GRPO group
success probabilities or establish transfer; they help identify errors and
within-question inconsistencies for the next iteration.

Preflight checks transport and API envelope availability. Valid API responses
with bad tool submissions or truncation are recorded as model outcomes and do
not block the formal probe. Transport failures block preflight; formal transport
failures are retained and cause the job to exit unsuccessfully. No requests are
retried. Native tool compliance alone does not establish semantic correctness.

## Results

Slurm log: `slurm-bp-tools-small-<jobid>.out`. The job prints `BP_RUN_DIR`, a fresh
directory under `runs/bp_probe_nus/<jobid>.<suffix>/`. Download that whole directory:

- `server_manifest.json`, `models.json`, `server.log`: actual environment,
  launch command, input token lengths and server startup.
- `preflight/` and `probe/`: raw messages including explanation/tool calls,
  finish reasons, token usage, timing, run config and protocol summary.
- `preflight.log`, `probe.log`: incremental progress, also echoed into Slurm stdout.
- `bundle/`, `run_probe.py`: exact runtime sampling inputs and launch code.
- `COMPLETE.json`: all requests completed without infrastructure failures;
  this is not a semantic correctness certificate.

Teacher labels remain locally in
`new/local_data/social_runs/bp_soc_probe_r1/tasks.jsonl`. After downloading to
`new/local_data/social_runs/bp_soc_remote_r1/`, local scoring is:

```bash
/private/tmp/social_native_tools_venv/bin/python -m training.b_sft.prepare_named_bridge_probe \
  --data new/local_data/social_runs/bp_soc_probe_r1 \
  --score-samples new/local_data/social_runs/bp_soc_remote_r1/probe/samples.jsonl \
  --out new/local_data/social_runs/bp_soc_remote_r1/local_scoring
```

The scorer verifies request/sampler hashes and task IDs before applying the
unchanged labels. Full returned responses are retained for reasoning analysis.
The source bundle was selected locally by `training/b_sft/prepare_soc_probe.py`
from `bp_readable_prompt_review_v2`; there is no remote regeneration step.
