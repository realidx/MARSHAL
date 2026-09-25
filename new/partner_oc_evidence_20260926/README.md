# D24v1 partner-choice O/C controls: training and CalBench

This package preserves the raw evidence for the O (`881810`) and C (`881811`)
40-update training runs and their frozen 24-game CalBench evaluations (`881966`,
`881967`). Native checkpoints and HF weights are not included in Git.

## Provenance and scope

- Training source commit: `ed1af650cbe475a42ae292db068e019f5c4f7eed`.
- Base model: `/home/e/e1300530/models/Qwen3-4B-Instruct-2507`.
- `data_reasoning_v6` manifest SHA256:
  `730f0d819b3a9e48cbcdc781b17cd5db580317d569f196ae0b97f2fb66e0729d`.
- Both runs used seed 42, the `micro24_v1_partner_choice_v1` pool,
  `standard_sequence` normalization, and one retained native checkpoint.
  Their base O/B/P+ mixture was 1:1:1; the extra micro-bank exposure differs:
  O uses `24v1_partner_o` and O-only micro rows (6 candidate groups/update,
  row weight 0.5); C uses `24v1_partner_c` and O/P micro rows (12 candidate
  groups/update, row weight 1.0). They are not pure O-only/P-only runs.
- O completed 40 updates and 796,665 generated response tokens against a
  planned 1,966,080-token budget. C completed 40 updates and 1,698,028
  tokens against 3,932,160 planned. Neither exhausted its planned budget.
- Native final checkpoints are `checkpoint-39` in the original run directories;
  both have `COMPLETE.json` manifests. Their corresponding HF exports were
  verified by full CPU `Qwen3ForCausalLM` loading and SHA256 checks.

## Frozen evaluation results

Both CalBench runs used the same 24-game stream suite on a single H100-96,
`VLLM_BATCH_INVARIANT=1`, temperature 0, 4,096 output tokens, 8 parallel games,
`max_num_seqs=32`, prefix caching on, chunked prefill off, cascade attention
off, and eager execution. Both finished 24/24 with healthy transport.

| Model | Job | Coordinated success | Successful and optimal | Mean headline score | Untruncated games | Strict envelope failures |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| O step-39 | 881966 | 3/24 | 1/24 | 0.459590 | 19/24 | 12 |
| C step-39 | 881967 | 3/24 | 1/24 | 0.472641 | 18/24 | 12 |

O succeeded on `loose_uniform_s1`, `loose_uniform_s3`, and
`replan_varied_s1`. C succeeded on `blocked_uniform_s2`, `loose_uniform_s2`,
and `loose_uniform_s3`. Their successful-game sets overlap only on
`loose_uniform_s3`. For comparison, the separate D24v1 `micro24-step39`
evaluation (`879033`) scored 9/24, 6/24 optimal, mean 0.630298; do not
confuse it with the later `decomposed-step39` (`881481`, 7/24, mean 0.504938).

## Files

- `training_o.tar.gz`, `training_c.tar.gz`: complete run logs other than native
  model/optimizer checkpoint directories. Include resolved configuration,
  environment, all 40 update metrics and calls, phase timings, probability
  warnings, Q0 and every 10-update validation with per-question outputs,
  checkpoint retention metadata, and training logs.
- `calbench_o.tar.gz`, `calbench_c.tar.gz`: full raw 24-game results, traces,
  events, transport logs, server logs, execution identity, and protocol.
  Regenerable `triton-*` caches are excluded.
- `provenance.tar.gz`: exact launchers, Slurm logs, checkpoint completion
  manifests, HF export verification reports, and run status JSON files.
- `SHA256SUMS`: checksums of the five archives.

Static validation improved more in O than C at update 40, but neither model
matched D24v1 on this external interaction test. These are descriptive
comparisons: the arms have different token exposure and output truncation;
training reward or static validation alone does not establish stable
social-reasoning gain.
