# Two-player native BENAC slice pilot

This pilot tries the proposed consequence-based slice definition in our own
two-player game. BENAC is generally **mixed incentive**, not zero-sum. The
initial source is the 100 already qualified two-player O roots in
`examples/social_mixed/interaction_bank_v1/tasks.jsonl`. Those roots were
selected for an older short-interaction exercise, so this is a method and
plumbing pilot, **not** an estimate of how often C or S occurs in randomly
generated BENAC games. No active training bank or paper file is changed.

## One definition for one or several decisions

For each entrance belief, freeze the certified native opponent policy. A
`k`-decision slice lets ego control its first `k` actual decision opportunities
on **every reached branch**. After that, the selected ego teacher policy takes
over until native termination. Both the opponent policy and this exit rule are
the same for all compared policies and information conditions.

Let `J_k(pi)` be ego's expected terminal utility under a legal,
observation-contingent policy `pi`. We use:

```text
V*_k       = max_pi J_k(pi)
C_k(pi)    = V*_k - J_k(pi)
D_k(M)     = C_k(pi_M)
S_k(Z)     = V*_k(full information) - V*_k(mask private answer Z)
```

For `k=1`, forcing each root action then allowing the teacher to continue gives
the familiar action Q table and `C(a) = V* - Q(a)`. For `k>1`, `pi` chooses again
at the **state actually reached** after its first action. There is no sum over a
pre-recorded oracle path. The exact S calculation merges ego information cells
that differ only in the named private investigation answer; it retains the
public action tree, query cost, other signals, and frozen partner behavior.

Two S quantities are reported. `S` lets the oracle choose the root action;
`S_given_query` forces the root investigation action in both comparisons and
measures the value of its answer. A positive `S_given_query` does not by itself
mean that buying the query is optimal. At `k=1`, the teacher continuation after
the window may still use the answer, so the within-window S can be zero even
when the full-game answer has value. This scope is explicit in every record.

## Candidate and length selection

The CPU builder recomputes every candidate's native oracle and checks its
action Q table against the source teacher. It keeps the root C vector instead
of treating action count or game depth as difficulty. For a single-decision
slice, `C_max` records the largest root-action consequence. A continuous slice
can be consequential even when every root action ties: later actual decisions
can still affect the terminal outcome. The screen therefore retains roots with
`C_max > 0.1` **or** a later uniform-probe regret increment above `0.05`.

For a fixed, model-independent **uniform-action probe**, the builder computes
its regret when it controls the first 1, 2, or 3 ego decisions, with the teacher
handling the tail. An extension is useful when the extra controlled decision
increases this probe regret by more than `0.05`, or when it is the shortest
window in which a named answer has `S_given_query > 0.05`. The uniform probe is
only a way to find a reachable further consequence; it is **not model D** and
is not used as a claim about human or model difficulty. The small final panel
prefers distinct game families and has two roots per category: root action
choice, delayed consequence despite a flat root, positive information value,
and a zero-value information control with an uncertain answer. Each selected
root retains a `k=1` slice and one selected continuous slice.

## CPU result

Run from the repository root:

```bash
python -m new.benac_slice_pilot.build --per-mode 0
python -m unittest new.benac_slice_pilot.test_pilot -v
```

The checked-in `pilot_data/` contains exact candidate values, exclusions,
selected roots, source hash, thresholds, and the reference policy hash. The
full scan certified all 100 existing short-interaction roots; 95 had root
`C_max > 0.1`. Four of the five remaining roots have zero root regret but a
later uniform-probe regret increment above `0.05`; these would be lost by a
single-point C filter. Thus **99 of 100 pass the consequence screen**. The
eight selected roots are an intentionally capped diagnostic panel (two per
category), not the total number of eligible slices. Among 38 roots with legal
investigations, 14 had a selected answer with `S > 0.05` at the longest window.
These counts apply only to the preselected source bank; they are not
game-population rates. The eight selected examples include:

| Root | Role | Root `C_max` | Selected `k` | Information value |
| --- | --- | ---: | ---: | ---: |
| `0149f59d9032e5adc95b-O` | action choice | 0.5 | 2 | — |
| `00bf2cbba65a880234f0-O` | delayed consequence | 0 | 2 | — |
| `04029cadb035db2d4346-O` | information use | 0.25 | 2 | `S=0.25` |
| `3b433413665eacf1b3ac-O` | zero-value control | 0.25 | 2 | `S=0` |

The zero-value control's named partner preference remains uncertain at entry;
zero means that knowing it cannot improve the oracle's policy value under this
fixed opponent. In `3b433...`, the second ego turn immediately follows the
query, so no partner action intervenes in the answer-use comparison. Native
rollout also confirms that changing the first action changes the second input.
The S implementation agrees with an independent native answer-use ablation on
a separate two-player fixture (`1/3` utility).

The length curve is useful even before querying a language model. For the
positive-information root `04029cadb035db2d4346-O`, the uniform probe's exact
regret at `k=1,2,3` is `0.232, 0.646, 0.880`; the named answer's exact `S` is
`0, 0.25, 0.25`. Thus the second controlled decision is the first one where
the answer matters, while a third decision adds action consequences without
adding further value for this answer. We retain all three CPU values; choosing
`k=2` in the small panel tests the shortest information-bearing window, not a
claim that the third decision is inconsequential.

## Fresh-generation check

The existing bank was preselected for a different exercise. A separate seeded
generation check uses the native two-player generator and oracle without
filtering seeds by C or S:

```bash
python -m new.benac_slice_pilot.fresh
python -m new.benac_slice_pilot.build \
  --source new/benac_slice_pilot/pilot_data_fresh/source_tasks.jsonl \
  --out new/benac_slice_pilot/pilot_data_fresh/analysis \
  --per-mode 0 --per-group 1
```

For the fixed seeds 501–518, one root passed the finite-oracle and bounded-tree
checks; 17 exclusions are recorded (six three-player games and 11 solver
cycles). The accepted root has `C_max=0`, yet its uniform-probe regret is
`0, 0.254, 0.554` at `k=1,2,3`. It therefore **is** a continuous consequential
slice, selected at `k=2` by the revised screen. The small fresh sample says
nothing about prevalence; its value is exposing the failure of a root-only
filter without selecting seeds on the resulting C/S labels.

## Measuring the current model D

`model_probe.py` uses the existing native O prompt and tool decoder. It will
query an OpenAI-compatible model for every feasible length `k=1,2[,3]`, let
actual model actions advance the game, and let the selected teacher handle ego
turns after `k`. For `k=1`, action regret is read exactly from the root C
table. For longer windows, the probe estimates `V* - terminal utility` over
sampled hidden worlds and partner behavior. All lengths use paired entrance
worlds and rollout seeds, making the extra consequence of each controlled
decision visible.

For each information root, a second paired experiment **forces the selected
investigation as the first controlled action**, then asks the model to make
the remaining decision with the answer either shown or hidden. The arms share
the same physical game, entrance world, public history at that decision, and
partner policy; later histories can diverge with the model's actions. The paired payoff
difference tests whether the model uses valuable information and whether a
zero-value answer distracts it. We also record whether the unforced model
chooses to investigate. The forced root query counts toward `k`. Invalid,
truncated, and transport failures are reported separately; no terminal utility
is invented for them. Reported terminal regret is conditional on completed
trajectories, so completion rates must accompany it. The CPU result above
contains **no language-model D measurement**.

On an existing compatible local server:

```bash
python -m new.benac_slice_pilot.model_probe \
  --selected new/benac_slice_pilot/pilot_data/selected.jsonl \
  --candidates new/benac_slice_pilot/pilot_data/candidates.jsonl \
  --base-url http://127.0.0.1:8000/v1 --model MODEL_NAME \
  --checkpoint-hash CHECKPOINT_SHA256 --replicas 16 \
  --max-tokens 1024 --concurrency 8 --seed 42 \
  --output /absolute/path/to/new-output-dir
```

For the existing SoC H100 environment, after Git sync to a **clean** checkout:

```bash
sbatch --partition=gpu --gres=gpu:h100-47:1 \
  --export=ALL,PILOT_REPLICAS=16,PILOT_MAX_TOKENS=1024 \
  new/benac_slice_pilot/sbatch_probe.sh \
  "$PWD" /home/e/e1300530/models/Qwen3-4B-Instruct-2507 \
  /absolute/path/to/new-output-dir
```

The submitted script verifies the exact source-bank hash before GPU work,
records the Git commit and model SHA256, starts one local vLLM tool server,
runs the closed-loop probe, then stops the server. Use a new output directory
for every run. These commands prepare measurement; this repository does not
contain a completed language-model D result for this pilot yet.

To probe the separate fresh root on the cluster, set
`PILOT_PANEL_DIR="$PWD/new/benac_slice_pilot/pilot_data_fresh/analysis"` in the
Slurm environment and choose a different output directory. The script reads
that panel's summary and verifies its own source hash.

## Scope

The oracle is a selected, certified finite-game profile, not a proof of a
unique equilibrium. C and S here are relative to its fixed opponent strategy
and the stated entrance prior. S currently applies only to **private
investigation answers**; public-history information contrasts need a different
intervention because they can change what the opponent observes. The pilot's
small panel is for testing definitions and execution, not for training-scale
selection or cross-domain claims.
