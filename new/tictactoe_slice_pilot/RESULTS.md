# Qwen3-4B-Instruct-2507 strategic slice pilot

## Task and fixed protocol

Measure the initial model's action distribution on 128 frozen, symmetry-distinct
Tic-Tac-Toe decisions, with 32 decisions per structural category and 16 draws
per board. Rank decisions by empirical expected exact minimax regret among
valid legal-action completions, requiring at least eight valid samples. This
is a diagnostic panel, not a prevalence estimate over naturally visited games
or a direct measurement of the model's reasoning process.

Model: `/home/e/e1300530/models/Qwen3-4B-Instruct-2507`. Checkpoint SHA256:
`dd47a409e12fea80e2656323913f90d1cfca0d3baf339d54fba7177a1a13940c`.

Both runs use the same prompts, panel, per-board/per-replica seeds, temperature
0.7, top-p 0.8, top-k 20, concurrency 16, and stop string `</answer>` (included
in the output). The prompt requests a brief `<reason>` followed by an
`<answer>`. Oracle regret uses discount 0.9; outcome values at discount 1.0
are retained in the frozen scoring key. The only intended protocol change is
the completion budget, 600 versus 1024 tokens.

SoC runtime: `/home/e/e1300530/tmp/marshal-vllm09`, Python 3.10, vLLM 0.28.0,
Torch 2.13.0, Transformers 5.16.1; single H100-47 in the `gpu` partition,
TP1, BF16, eager, batch invariant enabled. Nodes differ between runs, so
matching seeds does not constitute a guarantee of token-identical generations.

## Completed runs

| Metric | 600 tokens | 1024 tokens |
|---|---:|---:|
| Slurm job | 893809 | 893851 |
| Node | xgpi14 | xgpi13 |
| Elapsed | 10m55s | 14m16s |
| HTTP successes | 2048/2048 | 2048/2048 |
| Valid legal actions | 1613 (78.76%) | 1776 (86.72%) |
| Truncated outputs | 433 (21.14%) | 270 (13.18%) |
| Other invalid outputs | 2 | 2 |
| Rank-eligible boards | 107/128 | 118/128 |
| Error rate among valid actions | 40.48% | 39.47% |

Both jobs completed with exit code 0 and a root `COMPLETE.json`. Invalid
samples include truncations; they are excluded from canonical game regret.
Completion alone does not establish that every board meets the ranking threshold.

| Category | Eligible, 600 | Eligible, 1024 | Valid-action error %, 600 | Valid-action error %, 1024 |
|---|---:|---:|---:|---:|
| immediate_win | 27/32 | 32/32 | 53.48 | 51.27 |
| immediate_threat | 29/32 | 31/32 | 58.89 | 56.06 |
| non_immediate_split | 26/32 | 28/32 | 46.67 | 47.95 |
| flat | 25/32 | 27/32 | 0 | 0 |

Category error rates pool valid samples across all 32 category boards; ranking
coverage separately applies the eight-valid-sample threshold. Flat-board zero
regret is definitional and does not certify strategic reasoning.

## Interpretation

Increasing the budget reduces truncations by 163 responses (7.96 percentage
points) and adds 11 eligible boards, with no previously eligible board lost.
On the 107 boards eligible in both runs, mean board-level expected regret is
0.4720 at 600 tokens and 0.4559 at 1024. These are conditional estimates, not
a causal or statistically established improvement in game skill.

The top-20 board sets are identical, though their order changes: 12 immediate
wins, seven immediate threats, and one non-immediate split. Large losses remain
concentrated in direct tactical positions in this panel.

The highest-regret board is `..O.XOXX.`, O to move. Playing `O(2,2)` wins
immediately. Both runs choose `O(0,0)` in all 16 samples, with regret 1.9;
that move loses under optimal continuation.

In the 600-token run, all 433 truncated responses consume the full budget,
and 428 never close their `<reason>` section. Inspected examples repeatedly
revise board interpretations or legal moves before producing an answer. This
supports explanation overrun as a proximate failure mode, not a claim that
raising the cap alone fixes the strategy errors.

## Evidence and engineering fixes

Raw requests, model responses, completion markers, runtime source manifests,
and full score files remain in the local run directories and are not included
in this branch. Before publication, both runs were rescored under Python 3.10
from their retained samples; the score summaries and rankings reproduced
byte-for-byte. This report contains aggregate results and one illustrative
board, without publishing the raw response archive.

The initial smoke job 893797 completed all eight HTTP calls without truncation
or invalid actions, then failed scoring because the original analyzer used a
Python-3.12-only f-string. Its responses were subsequently scored successfully
in Python 3.10. That failed job is not represented as an end-to-end success.
The repaired analyzer and Slurm spool-path fix were used for both full runs.

CPU checks reproduced all five frozen data files byte-for-byte under Python
3.13 before the compatibility repair. After repair, Python 3.10 reproduces
requests, summaries, action values, regrets, categories, and board selection;
the only data difference is uniform-policy mean rounding up to 2.22e-16. The
committed frozen data is unchanged. Syntax and whitespace checks pass.
