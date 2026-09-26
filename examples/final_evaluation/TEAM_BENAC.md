# Same-checkpoint BENAC teams and reference opponents

## Ready: same-checkpoint teams

Each seat is an independent agent with its own private information. All seats
use the same checkpoint. One rollout per frozen instance, temperature 0,
batch-invariant serving required, 1024 output tokens, at most one protocol
retry. No change to native rules or prompts.

| Players | Frozen suite | Games | Goals | Commitments per player | Proposal opportunities per player |
|---|---|---:|---:|---:|---|
| 2 | `team_benac_2p_v1` | 16 | 3 | 2 | 2 or 4 |
| 3 | `team_benac_v1` (unchanged) | 16 | 3 | 2 | 2 or 4 |
| 4 | `team_benac_4p_v1` | 16 | 3 | 2 | 2 or 4 |

New size suites cross binary/linear × 2/4 rounds × balanced/avoid-heavy priors
× two instances. Prior weights (want, neutral, avoid) are (1,1,1)/(1,1,2).
Native connected goal structures involve all players; two-player goals use
arity 2, four-player goals use arity 2 or 3. Frozen instances are not selected
by model output, utility or teacher solvability. Geometry overlap is audited
against the original suite's historical bank inventory. Seen/unseen counts
are observations of this audit, not forced balanced strata or per-model IDs.
Different size suites are not identical-difficulty paired environments.
Report each size separately, including completion, conditional team/per-player
utility, full-cohort failure bounds, invalid calls and truncation.

Run from the repository root against an existing service:

```bash
TEAM_SUITE=examples/final_evaluation/team_benac_2p_v1 \
  bash examples/final_evaluation/run_team_benac.sh BASE_URL MODEL HASH runs/team2-MODEL

# Default is the unchanged three-player suite.
bash examples/final_evaluation/run_team_benac.sh BASE_URL MODEL HASH runs/team3-MODEL

TEAM_SUITE=examples/final_evaluation/team_benac_4p_v1 \
  bash examples/final_evaluation/run_team_benac.sh BASE_URL MODEL HASH runs/team4-MODEL
```

The new 2/4-player suites passed all 32 native random-action rollouts locally;
the 16 original 3-player smoke rollouts also pass. These are implementation
checks, not LLM performance results. Four-player prior enumeration is larger;
start with `TEAM_PARALLEL_GAMES=1` if host memory is constrained.

## Implemented but not ready: two-player reference opponent

One LLM faces one fixed same-information reference player, rotating both
focal seats: 16 instances × 2 seats = 32 games/model. The reference policy
maximizes its own utility with the private teacher's response tie convention;
it is not a team-optimal or omniscient upper bound. All models share the
same compiled policy. The model is not told the partner's hidden type.

The compiler enumerates the complete public action tree using the full public
prior before any model run. Its information-set audit requires identical
policy probabilities for worlds sharing the player's own preferences and
received private answers. Runtime lookup uses only those facts. All legal
LLM actions advance the precompiled tree, even if assigned zero probability
by the reference; off-path beliefs follow the teacher's prior conditioned on
own type and private answers. No re-solving against a particular tested model.
Reference ties use a fixed seeded draw keyed by case, focal seat and tree node.

**Local preflight:** all 16 standard two-player instances exceed 10,000 nodes
(with a 10-second per-case budget). See `oracle_preflight_2p_v1.json`.
A small one-round fixture passes native integration, information-set checks,
and legal off-policy traversal, but this does not certify the full suite.
Do not launch the reference evaluation until the entire chosen suite passes.
The runner rejects incomplete, failed or hash-mismatched policy bundles; it
never silently substitutes a heuristic or excludes hard instances.

```bash
# CPU-only compilation. This currently fails on the full standard suite at
# the stated budget. Larger budgets may require substantial time and memory.
python -m examples.final_evaluation.team_oracle \
  --suite examples/final_evaluation/team_benac_2p_v1 \
  --output runs/reference-policies-2p --seconds 30 --max-nodes 10000

# Only after every instance has a certified policy:
python -m examples.final_evaluation.run_team_oracle \
  --suite examples/final_evaluation/team_benac_2p_v1 \
  --policies runs/reference-policies-2p \
  --base-url BASE_URL --model MODEL --checkpoint-hash HASH \
  --output runs/reference-2p-MODEL --batch-invariant-confirmed
```

The reference group reports focal utility as well as team utility, failures
and full-cohort bounds. A shorter, separately frozen oracle suite or a scalable
solver is needed if the full suite remains infeasible; neither is silently
substituted for this experiment.

## Ready: bounded-depth reference

Use `--reference bounded` to bypass full-terminal compilation explicitly. This
is a **bounded-depth reference player**, not an exact oracle. The full game,
16 instances, two focal seat assignments (32 games/model), LLM prompt, output
budget and decoding settings remain unchanged.

```bash
python -m examples.final_evaluation.run_team_oracle \
  --reference bounded \
  --suite examples/final_evaluation/team_benac_2p_v1 \
  --base-url BASE_URL --model MODEL --checkpoint-hash HASH \
  --output runs/bounded2-MODEL --batch-invariant-confirmed
```

The fixed reference configuration is:

- Replan at each reference decision over two completed proposal opportunities.
  A pending offer's response is resolved before advancing the counter; no
  unresolved offer is evaluated at a cutoff. The horizon shrinks at game end.
- At the cutoff use native current commitment utility (binary/linear and signed
  preferences). This is a terminal-value approximation, not added game reward.
- Predict the focal player with a fixed one-proposal myopic policy. Offers are
  valued using predicted immediate accept/reject responses. Each predicted
  actor maximizes expected own utility conditioned on its own type and private
  query answers; response ties prefer others' utility. A fixed 0.05 uniform
  tremble assigns positive probability to every legal action. Investigation
  has no immediate information bonus in this predictor.
- Bayesian likelihoods for actual focal actions use that same predictor.
  Reference actions are interventions, not evidence about the other player.
  Truthful query answers condition the receiver's information set only. No
  realized hidden opponent preference is passed to action selection.
- Inside a hypothetical window, the predictor conditions on the window-start
  filtered prior, own preferences, and simulated private query answers; it does
  not infer additional information from hypothetical public actions. The
  reference best response does account for the fixed predictor's action
  likelihoods and chooses contingent actions by information set.
- The reference computes an information-set best response to this predictor,
  rather than iterating both players to an equilibrium. Remaining reference
  ties use a seeded uniform draw, fixed across tested checkpoints.

The epsilon, horizon, belief convention, tie rules and implementation hash
are recorded in the output protocol. Node counts and root action probabilities
are recorded per reference action. Resource failures stop evaluation; there is
no implicit fallback to a shallower search. As with every short-horizon
baseline, delayed binary goals and information gathering can be undervalued.
Report this condition separately from homogeneous teams and exact reference
policies; do not describe it as an optimal-performance bound.

Validation: all 16 two-player instances × both focal seats completed with a
scripted random legal-action focal player (32 full games, no LLM calls).
Hidden-world invariance, positive predictive likelihoods, own-action belief
invariance and proposal-depth boundaries passed. These are implementation
checks, not empirical evidence of opponent strength.
