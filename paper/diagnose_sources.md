# Current manuscript diagnosis: v9 Q0

This inventory supersedes the previous v6 and native-endgame manuscript sources.

- Archive: `new/diagnostic_v9_results_20260926/raw_runs.tar.gz`
- Members: `runs/diagnostic_v9/q0-882149/structure_v9/`
- Model: unchanged Qwen3-4B-Instruct-2507; one repeat, 22 cases, 88 calls.
- Cases and certificates: `new/diagnostic_v9/cases.json`.
- Scoring and aggregation: `new/diagnostic_v9/experiment.py`.
- Qualification: `new/diagnostic_v7/build.py:qualify`, reused by v9.
- Machine-readable numbers, raw-member hashes and protocol: `paper/diagnose_results.json`.

## Manuscript mapping

- Main table: `summary.json` panels `repair_sensitive`, `action_control`, and four evidence layers. Denominators include invalid outputs.
- Inference failures: per-case B support and favored fields; direct feedback 6/6 joint, elimination 0/6, multi-update 0/4.
- Planning failure: P_gold 11/22; exact mean regret 0.5665558019216556.
- Intervention: 21 valid pairs, 10 changed judgments, 9 changed actions. Gains: 3 positive, 17 zero, 1 negative overall; among changed judgments: 3 positive, 6 zero, 1 negative. Mean gain 1/7 overall, 0.3 on changed judgments.
- Repair-sensitive: eight valid pairs, two action changes, one positive gain of 1, mean 0.125. Controls: thirteen pairs, two positive gains (2 and 1), one negative (-1), mean 2/13.
- Appendix-only partial-repair example: `interaction-0524ffa3f232ff556a`. P_model action index 4, value 0; P_gold index 2, value 1; optimal index 5, value 2. Checked against raw tool calls and case action table. This illustrates partial repair, not a fully successful plan.
- Worked-example audit: recomputing `InitialEpisode(raw, initial_state)` reproduces policy hash `4376ca0e49ce1bbd012a97742650cee326157d51e8a42b41430124cd9ca47baa`. The observed initial offer (Blair adds nothing, Alex adds Cedar) has likelihoods `(1/13, 0, 0)` under Want/Neutral/Avoid and Blair continuation values `(1, 0, 0)`. The alternative initial offer (Blair adds Maple, Alex adds Cedar) yields Blair `(1, 1, 1)`. Alex accepts either offer with probability one. These quantities support the posterior and payoff explanation in `diagnose_appendix.tex`.

The paired regret/value identity and equality of the two planner requests' seeds and tools were checked for all cases. The single P_model format failure is excluded only from paired utility statistics. The diagnostic covers seven reused geometries; cases are not independent transfer samples. Action controls are not guaranteed model-invariance controls. Do not pool these results with old 16-case v6 voluntary histories or claim uniformly beneficial repair.

- Main-text two-goal example: `layer-19646c73e0c97ae729` (action control). Recomputed observed-offer likelihoods are `(1/6, 1/9, 0)`, giving posterior `(0.6, 0.4, 0)` from a uniform prior. Raw inference says Avoid only. P_model requests no own addition and Blair Maple (index 2, utility 0); P_gold requests Alex Maple and Blair Cedar (index 4, utility 2, optimal). The gain demonstrates a beneficial input intervention, not that correct inference is necessary to choose the optimal action.
