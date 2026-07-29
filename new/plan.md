# Value-Oriented Credit Assignment For Interactive Reasoning

## Thesis

Do not frame this as "training an LLM to play games." Frame it as:

> Games are controlled interactive environments for studying long-horizon credit assignment. Each game targets a specific reasoning primitive, and value-based feedback converts delayed outcomes into local decision and, later, reasoning-span credit.

MARSHAL is the closest baseline:

```text
MARSHAL: delayed outcome -> turn-level reward
Ours: game/information-state value -> decision-level credit -> optional span-level process credit
```

The key claim must stay conditional: games do not automatically improve general reasoning. Transfer must be tested on tasks that require the same primitive.

## Ability-Driven Curriculum

Organize by ability, not by game.

| Game | Target Ability | Credit Signal | Transfer Tests |
|---|---|---|---|
| TicTacToe | deterministic planning, lookahead, threat/block detection | exact minimax, depth-sensitive value, regret | multi-step math, code planning, deterministic tool planning |
| Connect Four | deeper lookahead, traps, delayed tactics | approximate minimax/MCTS value | longer planning and search tasks |
| Kuhn Poker | imperfect information, belief reasoning, mixed strategy, opponent modeling | information-state CFR value, policy advantage, exploitability | theory-of-mind, hidden-state inference, adversarial dialogue |
| Leduc Poker | multi-round belief update, public/private evidence | CFR or approximate information-state value | multi-turn belief revision |
| Mini Hanabi | cooperation, communication, partner modeling, information value | rollout/belief value, counterfactual team score | multi-agent collaboration, tool delegation |
| Matrix/social games | payoff reasoning, preference modeling, deception/identity inference | payoff or role-inference value | negotiation, social reasoning |

Core interpretation:

- TicTacToe asks: "What happens several steps after this action?"
- Kuhn asks: "How should I act under hidden information and stochastic/mixed strategies?"
- Mini Hanabi asks: "What does my partner know, and should I act or communicate?"

## MARSHAL Hook Points

The existing repo already supports per-turn reward injection.

- `roll/agentic/rollout/env_manager.py`
  - `_log_env_state(...)` records one scalar `reward` for the current player's action.
  - `_formulate_single_rollout(...)` collects rewards as turn `scores`.
  - `get_masks_and_scores(...)` places turn scores at `<|im_end|>` when `use_turn_scores: True`.
- `roll/utils/functionals.py`
  - `reward_postprocess_agentic(...)` normalizes/clips rewards.
  - `compute_advantage(...)` computes REINFORCE/GAE over the response mask.

So the first prototype should change reward generation, not the trainer.

## Reward Models

Use a shared abstraction:

```text
state or information state -> legal action values -> local credit
```

Preferred reward modes:

```text
potential_delta = V(after) - V(before)
centered_q = Q(chosen) - mean_a Q(a)
regret = Q(chosen) - max_a Q(a)
```

Use regret carefully: it is non-positive and can be wrong for mixed-strategy games.

Game-specific choices:

1. **TicTacToe**
   - Use exact minimax, not `data/tictactoe_value_table.json` because that table is MCTS/terminal-return based.
   - Include depth-sensitive values so progress toward faster wins and delayed losses is visible.
   - This is a sanity check, not evidence of general reasoning.

2. **Kuhn Poker**
   - Use information-state value: private card + public betting history.
   - Use CFR/Nash policy value or CFR-policy advantage.
   - Do not use hidden full-state value that leaks the opponent's private card.
   - Avoid pure max-regret as the only reward because equilibrium can require mixed strategies.

3. **Mini Hanabi**
   - Use approximate rollout or belief-state value over expected team score.
   - Reward the counterfactual value of acting, discarding, or communicating.
   - Avoid heavily hand-coded heuristics except as explicit ablations.
   - Do not call it an exact oracle unless an exact solver/table is actually built.

For general-sum/cooperative games, always specify the solution concept: team score, welfare, partner-model value, exploitability, or counterfactual improvement.

## Prompt Robustness

Prompt randomization is useful but not proven to solve overfitting. Treat it as an ablation.

Randomize:

- rule prompt templates, with held-out templates for eval
- auxiliary rule hints
- board/state renderings
- action surface forms mapped to canonical action ids
- symbol names and player roles
- opponent/partner wording

Measure:

```text
generalization_gap = seen_prompt_score - held_out_prompt_score
```

If randomization only improves seen-prompt performance, it is not evidence against overfitting.

## Span / Prefix Probing

Span probing should be a second-layer diagnostic before it becomes a training reward.

For a reasoning prefix `z_{\le t}`:

```text
U_t = sum_a pi(a | s, z_{\le t}) Q(s,a)
delta_t = U_t - U_{t-1}
```

Immediate `delta_t` rewards spans that directly shift action probability toward better actions. It can miss setup reasoning such as:

```text
I should consider what the opponent will do.
```

Use delayed span credit:

```text
credit_i = sum_{t >= i} lambda^(t-i) delta_t
```

For analysis, use counterfactual ablation:

```text
credit(span_i) = U(full_reasoning) - U(reasoning_without_span_i)
```

Cost:

```text
num_spans * num_legal_actions * action_string_length
```

This is feasible for TicTacToe and Kuhn. Rollout-based probing is much more expensive and should not be first.

Training rule, only after offline validation:

```text
total_reward = action_value_credit + alpha * normalized_span_credit
```

Keep `alpha` small so noisy process rewards do not dominate action correctness.

Baselines:

1. outcome-only MARSHAL
2. turn-end oracle reward
3. immediate prefix-delta reward
4. lambda-return span reward
5. counterfactual span ablation as analysis

Prior-work lessons:

- PRMs/PRM800K: direct process labels are expensive.
- Math-Shepherd-style methods: continuation sampling gives automatic step quality but is costly.
- MCTS/value methods: useful but introduce approximation.
- Free/process-from-outcome approaches: possible, but must be checked against final correctness.

## Experiments

Minimum experiment ladder:

1. **Sanity check**
   - TicTacToe exact minimax reward.
   - Verify action optimality, regret, and prompt robustness.

2. **Ability reward models**
   - TicTacToe: planning value.
   - Kuhn: information-state CFR value.
   - Mini Hanabi: rollout/belief team value.

3. **Prompt robustness**
   - fixed prompt vs randomized prompt vs randomized state/action forms.
   - evaluate seen and held-out templates.

4. **Span probing**
   - first offline `U_t` curves.
   - then lambda-return span reward if curves are meaningful.

5. **Transfer**
   - planning games -> math/code/tool planning
   - belief games -> hidden-state/theory-of-mind/adversarial dialogue
   - cooperative games -> multi-agent collaboration/tool delegation

Critical ablations:

```text
same games + same rollout budget + different credit assignment
same reward + same games + fixed prompts vs randomized prompts
ability-targeted training vs unrelated transfer tasks
```

## Claims

Defensible now:

- MARSHAL leaves intra-turn reasoning credit unresolved.
- Small games can provide cleaner local decision credit than terminal-only rewards.
- Different games stress different interactive reasoning primitives.
- Span probing is plausible but should be validated before training.

Needs evidence:

- non-game transfer
- span credit improves over turn-end decision credit
- approximate values are reliable enough for Kuhn/Hanabi-style training
- ability-targeted game training transfers more to matched tasks than unmatched tasks

Do not claim yet:

- "games improve general reasoning"
- "span probing solves token-level credit assignment"
- "all games have exact optimal values"
- "prompt randomization prevents overfitting"

## Immediate Next Steps

1. Implement exact TicTacToe minimax as a sanity check.
2. Add a generic `InteractionCreditOracle` interface.
3. Add prompt/state/action randomization with held-out template evaluation.
4. Build Kuhn information-state CFR value.
5. Prototype Mini Hanabi rollout/belief value.
6. Run offline span-probing diagnostics before adding span reward to training.
7. Choose ability-matched transfer benchmarks before any large run.
