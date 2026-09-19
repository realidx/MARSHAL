# Single-domain ablations and B/P → SP

Arms: `b_only`, `p_only`, `bp`, `selfplay`. New ablations use v6 and the stable objective unchanged. Eight responses/question, target eight effective groups total/update, maximum 32 candidate groups. B/P splits eight targets 4+4; a single domain uses all eight and loss weight 1. Total generation tokens, not update count, are the comparison budget. B-only retains the same B scaffolds/stage rotation as BP; P-only sees no B tasks. Validation remains the common unassisted panel and self-play diagnostics, without training on it. Best-checkpoint score uses only B kernel/mode mean for b_only and P kernel/mode mean for p_only; ties retain the earlier checkpoint. Last checkpoint remains available.

After committing/syncing the code on SoC:

```bash
bash examples/social_mixed/submit_soc.sh h100-96 b_only
bash examples/social_mixed/submit_soc.sh h100-96 p_only
```

These are submission entries, not a claim that the outstanding whole-suite/preflight and GPU acceptance issues are resolved.

## B/P → SP

1. Preselect B/P checkpoint by fixed dose or frozen internal-validation rule; record its HF export path/hash, first-stage tokens and data version. Do not choose by CalBench.
2. Start a fresh selfplay run with SOCIAL_MODEL set to the BP HF export, not the native optimizer checkpoint. Do not supply submit_soc.sh's third resume argument. Actor and frozen reference both initialize from this export; old-policy means the current rollout policy and is different.
3. New optimizer, cosine horizon, SP baseline and counters; stage-zero validation is mandatory. Compare this baseline with the exported BP model's evaluation under identical settings before interpreting degradation as SP learning.
4. Set the SP-stage token budget explicitly. Report sum of both stages as total compute. For equal-total-budget claims compare against a SP-only run with that total budget, not merely the shorter SP second-stage budget.

```bash
SOCIAL_MODEL=/absolute/path/to/bp_hf_export \
SOCIAL_TOTAL_TOKENS=3276800 \
bash examples/social_mixed/submit_soc.sh h100-96 selfplay
```

3276800 is an example second-stage budget, not an automatically selected allocation. No replay of B/P labels is added in stage two. The reference constrains visited SP contexts; it does not guarantee B/P retention.
