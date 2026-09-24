# D interaction-training chains and D-25 CalBench

This bundle preserves original logs from both runs of the opt-in D interaction
pipeline. It contains no native checkpoint weights, optimizer states, HF
exports, or Triton compilation cache.

| Evidence | Source job | Source commit | Updates | Response tokens | Status |
| --- | --- | --- | ---: | ---: | --- |
| `training/d0-25-877247.tar.gz` | 877247 | `da0e67050ffa6e5a8832e08fa41940deccd1e7b1` | 26 (steps 0–25) | 1,274,448 | Paused |
| `training/d0-43-878558-fixed.tar.gz` | 878558 | `e157e25dfa92709fc119039be5604cac4f411cd8` | 44 (steps 0–43) | 2,150,054 | Paused |

Both jobs started from Q0, used the same `interaction_bank_v1/tasks.jsonl`
SHA256 (`37063c55133f6b3b1c159a77a271886e9d5daafb22711935baa684241f033dd1`)
and the same data manifest SHA256
(`730f0d819b3a9e48cbcdc781b17cd5db580317d569f196ae0b97f2fb66e0729d`).
Each training archive includes all per-step calls, units, games, metrics,
validation, static-O monitoring, worker logs, resolved configuration, and
run/exit metadata. The Slurm stdout files are separate. The old checkpoint-25
weights were removed before this archive; the new checkpoint-43 completion
manifest is included separately, without its weights.

**Important:** job 877247 used `InteractionCollector` v1, which generated
static prompts with the default `name_variant=0` but scored against each
task's stored `name_variant`. This corrupted some task rewards and protocol
penalties. Job 878558 uses the `interaction-v2-name-contract` fix and rejects
v1 resume. The two runs are evidence of this wiring change, not a clean
data-only or method-only ablation.

`calbench/d25-877838-7of24.tar.gz` is the complete frozen-profile H100-47
CalBench run for the old job's D-25 HF export. It contains all 24 per-game
results, traces, events, transport logs, suite/protocol metadata, server log,
and top-level results; Slurm streams are separate. It exited 0 with **7/24**
coordinated, 4/24 successful and optimal, mean headline 0.479338, 24/24
healthy transport, 23/24 untruncated, and two strict envelope failures.
This test result does not repair the old training signal.

SHA256:

```
aa3c119e8982efaa522c8439a003c477e2a8c87293880ce97e2aa9a778c66ad8  training/d0-25-877247.tar.gz
83b18b7cfa7c52e95fcf29105019339e0c3b169ea997b0abb969a8dbf47694a8  training/d0-43-878558-fixed.tar.gz
f2359ea6f70fb0f2f9546d8016dcbced3a3a186da48e95f1d56a8d2127457011  training/checkpoint-43-COMPLETE.json
01106d31ce61aff98fa0da77ad796b11a7a8701a369ab7d2102b2c333f10e45d  training/slurm-social-decomposed-h10047-cross-877247.out
6a4df3a6da95831af52816d14d00f681c01d21a28e090207e3a9aa96069d8b1c  training/slurm-social-decomposed-h200-141-878558.out
f8fbac545ef6f7859f97eb5d9570ec17fe74d7e095163aee6f9ddd4c32eb7fcc  calbench/d25-877838-7of24.tar.gz
efa8d86cee52667b898f0467dcae7a97ffc832f7cfbd91726e67754d99ec99f3  calbench/calbench-new-d25-h10047-877838.out
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  calbench/calbench-new-d25-h10047-877838.err
```
