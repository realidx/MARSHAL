# 4B mixed B/P + self-play versus self-play only

This is the production entrypoint for the paired experiment. It reuses ROLL's
Megatron TP=2 optimizer, vLLM engines, weight synchronization and native
checkpoint implementation. It does not use the HTTP probe as training data.
No separate B/P warmup or accuracy gate precedes the mixed experiment.

## Fixed experiment

| Setting | Both arms |
|---|---|
| Initial policy and frozen KL reference | Qwen3-4B-Instruct-2507 |
| Training | BF16 full parameter, Megatron TP=2 / PP=1 / DP=1 |
| Sampling | Two TP=1 vLLM replicas, CUDA graphs, up to 16 active sequences per GPU |
| Generation | 1024 output tokens, temperature 1, top-p 1, no top-k/repetition restriction |
| Context | 4096; no silent input truncation |
| Optimizer | LR 1e-6 constant, Adam betas .9/.95, weight decay 0, clip .2, KL coefficient .01 |
| Microbatch / epochs | 1 decision; accumulate the entire collected batch; one update, one epoch |
| Main budget | 6,553,600 training response tokens per arm; includes invalid calls/retries |
| Collection target | At least 65,536 response tokens/update; finish complete reset groups |
| Saves | After first update, every 10 updates, final and signal-driven boundary |
| Native checkpoint retention | Latest two complete recovery points; all logs and validation records retained |
| Validation | Every 10 updates, fixed 8 B/P questions x2 and 2 full-game resets x2 |

The budget is not an exact count of updates: complete-game group boundaries cause
overshoot, which is recorded. Compare token-aligned checkpoints/curves and report
the actual generated tokens and elapsed time. The 1000-update setting is only a
safety ceiling, not a request for a 1000-update main experiment.

`mixed`: loss = .25 B + .25 P + .50 self-play. Each domain averages its units;
a self-play unit is one player's episode, averaging that player's decisions
(including retries). This prevents longer games/players with more turns from
silently setting the mixture. Each collection starts with 4 B and 4 P questions,
8 independent samples each, then 6 reset groups x4 games; additional full-game
waves fill the token target. B sampling has formation/update/maintain/update slots;
P covers its four pools, alternating investigation-positive/negative across updates.
There is no adaptive curriculum or selection by model success.

`selfplay`: identical mechanism, with no B/P training samples or loss. All players
use the current policy; all update jointly. No historical opponent pool in this
first experiment. Validation B/P never enters either optimizer.

At temperature=1 without truncating the sampling distribution, vLLM's saved
sampled-token log probabilities are the PPO denominator. The actor recomputes up
to 8 responses each update to log numerical/synchronization discrepancies. There
is no full redundant actor forward over the entire rollout, and no unused entropy
calculation. Actual native token IDs (not re-encoded HTTP text) form training rows.

## Data and failure semantics

Prepared train: B=152, P=128, 60 complete-game initial resets. Validation: B=33,
P=32, 12 complete-game initial resets. Direct factual B was excluded. No test data
is included. B/P inputs and labels are bound to the prior audited merged pack.
Self-play uses the existing zero-commitment reset bank, without solver or
model-success filtering. Its 60 resets come from a small number of templates;
this experiment does not establish broad structural generalization.

B/P: 1 correct, 0 incorrect/invalid/truncated, no retry or length penalty.
Self-play: player's own native terminal utility, private investigation and one
retry, -.1 per invalid/truncated submission separately recorded. No answer repair.
GRPO groups are same B/P question, or same reset AND player position across four
complete-game attempts. Never mix rewards across players or task domains.

If a game fails, its terminal utility stays null. If any replica in a self-play
group has missing utility, that group's outcome advantage is disabled; only its
separately observed protocol returns are centered and normalized. For fully
completed groups, own utility plus own protocol cost is centered and normalized.
This policy is identical in both arms and is logged as `outcome_incomplete_groups`.
Infrastructure failures stop the job; they are not converted into game rewards.

The frozen outcome implementation has isolated Python import names so it cannot
shadow the current B/P teacher in the same process. `prepare.py` changes import
names/path bootstrapping only, preserves source hashes, and does not call a solver.

## Local checks and upload

Completed locally: 72 reset replays with independent terminal-payoff recomputation,
privacy/retry/grouping tests, real TensorDict slicing and causal masks, CPU autograd
and microbatch weighting, both resolved configs. Using the existing 4B tokenizer,
1182 prompts were checked; maximum observed prompt length was 1894 tokens.
This does not substitute for a real CUDA update, distributed save/restore or
measured H100-47 peak memory. Those paths have not been executed locally.

The first allocated job checks imports/APIs and writes environment identity before
loading weights, then updates, saves and continues automatically. No manual
download/review is required to continue after the first update. Sampling and
training failures produce tracebacks rather than silent retries/reconfiguration.

From the Mac, the prepared bundle can be uploaded without committing unrelated work:

```bash
cd /Users/bruce/MARSHAL
rsync -avP -e 'ssh -J e1300530@stujump.comp.nus.edu.sg' \
  /private/tmp/marshal-social-mixed-v1.tar.gz \
  /private/tmp/marshal-social-mixed-v1.tar.sha256 \
  e1300530@xlogin.comp.nus.edu.sg:/home/e/e1300530/
```

On the SoC login shell:

```bash
cd /home/e/e1300530
sha256sum -c marshal-social-mixed-v1.tar.sha256
cd /home/e/e1300530/MARSHAL
tar -xzf /home/e/e1300530/marshal-social-mixed-v1.tar.gz
sbatch --job-name=social-mixed-4b --export=ALL,SOCIAL_ARM=mixed examples/social_mixed/sbatch_train.sh
sbatch --job-name=social-sp-4b --export=ALL,SOCIAL_ARM=selfplay examples/social_mixed/sbatch_train.sh
```

The default reuses the recorded `marshal` conda environment and H100-96 allocation
label. `--gres=gpu:h100-47:2` can override the resource request while keeping the
same model/microbatch. H200 GRES spelling must follow the cluster's actual labels;
do not guess it. The launcher preserves Slurm GPU visibility, does not install
packages, and never issues `ray stop --force` against other jobs. Old A100-specific
NCCL/CUDA paths are absent. A current CUDA-enabled environment with the existing
ROLL-compatible Megatron/vLLM adapters is required, not the inference-only vLLM09 env.

After local code edits regenerate the bundle before uploading:

```bash
/private/tmp/social_native_tools_venv/bin/python examples/social_mixed/bundle.py
```

Only rebuild data with `prepare.py` intentionally; it needs the local source
archives and eval split manifest, which are not necessary for remote training.

## Logs, pause and restore

Runs: `runs/social_mixed/<arm>-seed42-<jobid>/`. The launcher also writes
`mixed_latest.txt` and `selfplay_latest.txt`. Main files:

- `train.log`, `phases.jsonl`: initialization/rollout/ref/actor/update/save timings.
- Worker `startup-*.jsonl`: existing detailed startup diagnostics.
- `environment*.json`, `resolved_config.json`, `experiment.json`: reproducibility.
- `calls/`, `units/`, `games/`: original IDs, sampled log-probs, private observations,
  labels/rewards, player grouping and actual loss weights. Internal artifacts.
- `metrics.jsonl`: tokens, group diversity, failures, B skill accuracy, full-set errors,
  actor/vLLM log-prob discrepancy and optimizer progress.
- `checkpoints/checkpoint-N/COMPLETE.json`: native TP shards, optimizer, scheduler,
  RNG and pipeline state passed file completeness checks.
- `LATEST_CHECKPOINT`, `RESULT.json`, `EXIT_CODE`.

Slurm sends a warning 15 minutes before its time limit. The script forwards it to
the driver, which finishes the current optimizer batch and saves. If a step lasts
longer than that margin, the prior completed periodic checkpoint remains usable.
`paused` is distinct from completing the token budget. Resume uses a fresh output
directory and restores the original actor/optimizer/scheduler/RNG/cumulative token
counter; the frozen reference remains the initial 4B model.

```bash
cd /home/e/e1300530/MARSHAL
SOCIAL_OLD_RUN="$(cat runs/social_mixed/mixed_latest.txt)"
export SOCIAL_RESUME="$(cat "$SOCIAL_OLD_RUN/LATEST_CHECKPOINT")"
sbatch --job-name=social-mixed-resume --export=ALL,SOCIAL_ARM=mixed examples/social_mixed/sbatch_train.sh
unset SOCIAL_RESUME
```

To resume the control use `selfplay_latest.txt` and `SOCIAL_ARM=selfplay`. No
accuracy-based early stop is applied. A hard crash can lose work since the last
completed checkpoint; partial checkpoints cannot be resumed.
Full 4B optimizer states are large, so the default keeps the latest two complete
native checkpoints and removes their older staging hardlinks within that run.
Set `SOCIAL_KEEP_CHECKPOINTS` higher before submission if earlier checkpoints are
needed for later model evaluation; export an earlier candidate before it ages out.
Resuming never deletes checkpoints in the preceding run directory.

## A100 evaluation

Export a completed checkpoint on CPU using the SoC training environment (with
sufficient CPU RAM; avoid an unrestricted conversion on a shared login node):

```bash
python -m training.social_mixed.export /path/to/checkpoints/checkpoint-49 /path/to/hf-export
```

Copy the HF export to the A100 host. Serve the candidate on one GPU and the original
4B model on the other using the existing working vLLM environment, native Hermes
tool parser, max model length 4096, CUDA graphs and at most 16 sequences per GPU.
Keep the base opponent fixed across all checkpoints and both training arms.

```bash
python -m training.social_mixed.evaluate \
  --learner-url http://127.0.0.1:18091/v1 --learner-model social-learner \
  --opponent-url http://127.0.0.1:18092/v1 --opponent-model social-base \
  --output runs/social_eval/mixed-checkpoint-49
```

This evaluates all 65 B/P validation questions x4 and 12 validation resets, every
learner position x4 against frozen base opponents (112 full-game attempts). Report
own utility, others' utility, completion rate and protocol failures together; no
single win-rate claim. The initial-model baseline uses the base endpoint as both
learner and opponent. HTTP evaluation never feeds an optimizer. Final held-out
test evaluation remains separate from these validation-driven checkpoints.

Alternatively, start and stop both owned servers automatically on the A100 host:

```bash
cd /raid/chenjiahao/mas
CUDA_VISIBLE_DEVICES=6,7 TRITON_PTXAS_PATH=/home/chenjiahao/cuda-11.8/bin/ptxas \
  /raid/chenjiahao/conda_envs/mas/bin/python examples/social_mixed/a100_evaluate.py \
  --candidate /path/to/hf-export \
  --base /raid/chenjiahao/mas/models/Qwen3-4B-Instruct-2507 \
  --output runs/social_eval/mixed-checkpoint-49
```

For the initial-model baseline, set `--candidate` to the same original 4B directory.
Use this bundle on the A100 host too; only evaluation runs there. This launcher
checks port availability and cleans up only its own server process groups.
