# Single H100-96 terminal training smoke, 2026-10-06

Upstream game-slice e2cec0f. Qwen3-4B-Instruct-2507, full-parameter PPO,
32 trajectories/update (4 questions × 8), output 1024, context capacity 16384.
New h100-96-single profile: TP1, microbatch1, full recompute, actor/reference
offload, vLLM memory fraction .40. Existing two-GPU profiles are preserved.

Job 915648 and native-resume job 915674 both COMPLETED with exit 0 on xgpi5,
one H100 NVL (93.09 GiB). First update changed 60/145 checked norm tensors.
Both model/optimizer/RNG/sampler checkpoints have COMPLETE markers; resume
loaded the optimizer and RNG, selected four new questions, continued token
progress 17374 → 18014 and wrote checkpoint-1. Checkpoint files stay outside
the repository, approximately 52.46 GiB each. The LAST_CHECKPOINT files retain
absolute paths for audit. These are paused smoke runs, not final checkpoints.

First collection: 53 calls, 14 truncated (26.42%), none invalid; 18/32 completed
trajectories. Second collection: 32 calls, no truncation/invalid, all complete.
Different questions and lengths make these rates unsuitable for measuring
training improvement. Prompt explicitly requests brief reasoning before act.

First preupdate mean actor/behavior logprob difference .02089; clip fraction
1.1587%, exceeding the warning threshold 1%. Second: .000611 and 0%, no warning.
Finite probability warnings continue under the upstream protocol; they were
not suppressed. No NaN or OOM occurred. This does not prove all numerical
backend differences are harmless.

First train allocated peak 67.55 GiB, reserved 82.94 GiB; sampled whole-device
peak 87.38 GiB. Slurm MaxRSS approximately 206.22/242.90 GiB. Actual longest
sequences were short: consult summary.json; capacity 16K is not a tested
worst-case sequence length. Remaining GPU memory headroom is limited.

First rollout/reference/audit/update: 60.2/9.7/2.5/39.1 seconds; subsequent
update 9.2 seconds on much shorter responses. Weight sync ~28–40 seconds,
checkpoint ~139–143 seconds. Validation limited to two questions/parents,
every update for smoke. No full 96-slice validation, 6M-token completion or
final test. Full production timing cannot be established from two updates.

CPU suite: 29/30 passed, including terminal reward/credit, checkpoints, final
test lifecycle, native limits, actual Hydra/dacite profiles and batch weighting.
One unrelated historical social-mixed test rejects a stale prompt-source hash
for training/b_sft/social_named_probe.py. TerminalPipeline overrides the
collector and does not call that data loader; old labels were not rewritten.
Optional modelscope uploader is unavailable; configured filesystem uploader
worked. No packages installed or model downloads performed.

summary.json and per-job artifacts contain the original measurements, resolved
configs, source identities, environment, phase timings, checkpoint file markers
and probability warning. GPU telemetry cancellation at job teardown is expected;
the main batch jobs exited successfully.

Full CPU mock completed 25 updates covering all 100 selected questions; exact next-collection resume matched. See mock_CHECK.json. Synthetic tokens do not validate GPU behavior.
