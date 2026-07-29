# Understanding Reasoning Transfer from Game-Based LLM Post-Training

## 1. Motivation

Recent work suggests that post-training language models through game play can improve not only performance in the training game, but also performance on downstream reasoning tasks such as mathematics. This result is potentially important, but the mechanism behind the transfer remains unclear. Existing results do not yet explain:

1. what reasoning ability is acquired during game training;
2. how that ability changes the model's reasoning process; or
3. why the acquired ability transfers to a different domain.

A direct experiment would train an LLM in a game, evaluate it on mathematical reasoning, and compare its rollouts with those of the original model. However, the interpretation of such an experiment depends on the game-training method. If the training signal is arbitrary, any observed transfer may be specific to that method rather than evidence about what games contribute to LLM post-training.

The training method should therefore be derived from a reasoning requirement intrinsic to the game.

Tic-Tac-Toe provides a controlled starting point. To play well, an agent must evaluate how its current action changes future possibilities, anticipate the opponent's responses, and prefer actions whose future consequences are better. In other words, the game requires a form of thinking ahead.

This motivates the central question:

> Can an LLM acquire a reusable thinking-ahead strategy when it is trained with feedback that reflects the future consequences of each game decision, without being directly given the optimal action?

## 2. Core Hypothesis

Our hypothesis is that game environments can teach a reusable form of prospective reasoning:

> Training an LLM with decision-level feedback derived from future game consequences encourages it to compare possible continuations, and this learned reasoning strategy may transfer to non-game tasks that also require multi-step reasoning.

This hypothesis contains two distinct claims that must be tested separately:

- **Acquisition:** the training method changes how the model reasons about future consequences in the game.
- **Transfer:** the same change can be detected in downstream mathematical reasoning.

Improved game performance alone is not sufficient evidence for either claim. Similarly, improved mathematical accuracy alone does not identify the transferred mechanism. The analysis must examine both behavior and reasoning rollouts.

## 3. Research Logic

```text
The game requires reasoning about future consequences
                         ↓
The training signal assigns credit using those consequences
                         ↓
The model improves its decision-making in the game
                         ↓
We test whether its rollouts show stronger prospective reasoning
                         ↓
We test whether the same behavior appears in mathematical reasoning
                         ↓
We evaluate whether this mechanism explains cross-domain transfer
```

This logic does not assume in advance that game training produces genuine lookahead. The proposed reward gives future-consequence-aligned supervision; whether the model internalizes a transferable reasoning strategy is an empirical question.

## 4. Research Questions

1. Does game post-training change an LLM's use of prospective or thinking-ahead reasoning?
2. Does exact decision-level feedback produce a different change from terminal-outcome or turn-level training?
3. Can the change be detected in game rollouts rather than inferred only from win rate?
4. Does the same change appear in mathematical reasoning rollouts?
5. Does game training improve downstream reasoning after controlling for training tokens, optimization steps, and model-generated data?
6. Which properties of a game environment make it useful for teaching transferable reasoning?

## 5. Initial Scope and Assumptions

The initial study is deliberately restricted to Tic-Tac-Toe. It assumes:

- a deterministic, two-player, zero-sum game;
- perfect information;
- alternating actions;
- exact minimax evaluation using alpha-beta search; and
- a canonical terminal utility of \(+1\) for a win, \(0\) for a draw, and \(-1\) for a loss.

Intermediate environment rewards are zero. Any auxiliary reward used by the software environment, such as a positive reward for a draw or a formatting penalty, must be kept separate from the canonical game utility used in the formulation below.

A malformed or overlong model response is an artificial truncation rather than a legal Tic-Tac-Toe outcome. For such a transition, the canonical game reward is zero and the shaping potential is closed with \(V_i(s_{\mathrm{artificial\ terminal}})=0\). Formatting penalties are recorded separately as auxiliary rewards, and malformed trajectories are excluded from claims and metrics concerning preservation of the canonical Tic-Tac-Toe objective.

Because the game can be solved exactly, the continuation value has no estimation uncertainty. No confidence term is needed. Imperfect-information games and approximate search are outside the scope of the initial study.

## 6. Exact Depth-Sensitive Minimax Values

### 6.1 Notation

Let:

- \(s\) be a game state;
- \(P(s)\) be the player who acts in \(s\);
- \(\mathcal A(s)\) be the set of legal actions;
- \(T(s,a)\) be the successor state after action \(a\);
- \(r_i^{\mathrm{env}}(s,a)\) be the canonical environment reward from the perspective of a fixed player \(i\); and
- \(0 < \delta \leq 1\) be the game-step discount factor.

The subscript \(i\) always denotes a **fixed player perspective**. It must not change merely because the successor state belongs to the opponent.

### 6.2 Bellman Definition

Set the value of every terminal state to zero:

\[
V_i^*(s_T)=0.
\]

For a nonterminal state-action pair, define

\[
Q_i^*(s,a)
=
r_i^{\mathrm{env}}(s,a)
+
\delta V_i^*\!\left(T(s,a)\right).
\]

The state value is

\[
V_i^*(s)
=
\begin{cases}
\displaystyle \max_{a\in\mathcal A(s)} Q_i^*(s,a),
& P(s)=i,\\[8pt]
\displaystyle \min_{a\in\mathcal A(s)} Q_i^*(s,a),
& P(s)\neq i.
\end{cases}
\]

The maximization and minimization are both required because the value is maintained from player \(i\)'s perspective across the entire trajectory. Alpha-beta search computes these values exactly.

### 6.3 Outcome-and-Depth Interpretation

Equivalently, for an action evaluated under optimal continuation,

\[
Q_i^*(s,a)
=
o_i^*(s,a)\,
\delta^{d^*(s,a)-1},
\]

where:

- \(o_i^*(s,a)\in\{-1,0,+1\}\) is the minimax outcome for player \(i\); and
- \(d^*(s,a)\) is the number of game actions from choosing \(a\) through termination.

Thus, an action that immediately ends the game has \(d^*(s,a)=1\), so its value is exactly its terminal outcome. When \(\delta<1\), the value prefers faster wins and delayed losses while preserving

\[
\text{win} \succ \text{draw} \succ \text{loss}.
\]

When \(\delta=1\), the values distinguish only wins, draws, and losses; there is no preference over termination time.

## 7. Training Reward

For every environment transition \(s_t \xrightarrow{a_t} s_{t+1}\), define the training reward for fixed player \(i\) as

\[
r_{i,t}^{\mathrm{train}}
=
2r_{i,t}^{\mathrm{env}}
+
\delta V_i^*(s_{t+1})
-
V_i^*(s_t).
\]

Using the Bellman definition,

\[
Q_i^*(s_t,a_t)
=
r_{i,t}^{\mathrm{env}}
+
\delta V_i^*(s_{t+1}),
\]

so the training reward can also be written as

\[
r_{i,t}^{\mathrm{train}}
=
r_{i,t}^{\mathrm{env}}
+
\left[
Q_i^*(s_t,a_t)-V_i^*(s_t)
\right].
\]

The bracketed term is the exact minimax advantage of the selected action. Therefore:

- an optimal action has zero additional penalty;
- a suboptimal action receives negative decision-level feedback; and
- the canonical terminal outcome remains part of the objective.

The factor \(2\) in the original expression is not arbitrary. One copy of the environment reward is contained in the potential-based term through \(Q_i^*\), while the second preserves an explicit copy of the original game reward.

This construction uses exact future consequences to shape the reward, but it does not directly tell the model which action to output. The model must still learn the relationship between a state, its possible continuations, and the quality of its chosen action.

## 8. Preservation of the Game Objective

For a fixed player \(i\), define the discounted training return

\[
G_{i,0}^{\mathrm{train}}
=
\sum_{t=0}^{T-1}
\delta^t r_{i,t}^{\mathrm{train}}.
\]

Substituting the shaped reward gives

\[
\begin{aligned}
G_{i,0}^{\mathrm{train}}
&=
2\sum_{t=0}^{T-1}\delta^t r_{i,t}^{\mathrm{env}}
+
\sum_{t=0}^{T-1}
\delta^t
\left[
\delta V_i^*(s_{t+1})-V_i^*(s_t)
\right] \\
&=
2G_{i,0}^{\mathrm{env}}
-
V_i^*(s_0)
+
\delta^T V_i^*(s_T).
\end{aligned}
\]

Since \(V_i^*(s_T)=0\),

\[
G_{i,0}^{\mathrm{train}}
=
2G_{i,0}^{\mathrm{env}}
-
V_i^*(s_0).
\]

For a fixed initial state, the shaped return is therefore a positive rescaling of the original return plus a state-dependent constant. It preserves the ordering of policies under the canonical game objective.

This guarantee depends on three implementation conditions:

1. the player perspective \(i\) remains fixed while computing a return;
2. the same game-step discount \(\delta\) is used in the value function and the return; and
3. the potential is zero at terminal states.

## 9. Turn-Level Return Computation

The discount factor \(\delta\) refers to **game transitions**, not language-model tokens. The return from transition \(t\) must therefore be computed as

\[
G_{i,t}^{\mathrm{train}}
=
\sum_{k=t}^{T-1}
\delta^{k-t}r_{i,k}^{\mathrm{train}}.
\]

The implementation should:

1. precompute \(Q_i^*\) and \(V_i^*\) using alpha-beta search;
2. record the player-indexed shaped reward at every game transition;
3. calculate return-to-go at game-transition granularity; and
4. assign the appropriate turn-level training signal to the tokens generated during that player's turn.

The same fixed-player reward stream must include transitions taken by the opponent, even though no tokens from player \(i\) are generated at those transitions. If one shared model plays both sides, the returns for the two player perspectives should be constructed separately.

The implementation must not apply \(\delta\) once per token. It must also not feed an already discounted turn return into another discounted return-to-go calculation, because that would accumulate the same signal twice.

For this initial exact setting, there is:

- no state-wise standardization;
- no confidence term;
- no \(\lambda\)-weighted outcome/counterfactual mixture;
- no separately injected precomputed advantage; and
- no modification of the canonical terminal objective.

## 10. Diagnostic Measures

For diagnostics at turn \(t\), set \(i=P(s_t)\), so that the values are measured from the acting player's perspective and \(V_i^*(s_t)=\max_a Q_i^*(s_t,a)\).

The range of action values at a decision state is

\[
D_t
=
\max_{a\in\mathcal A(s_t)}Q_i^*(s_t,a)
-
\min_{a\in\mathcal A(s_t)}Q_i^*(s_t,a).
\]

\(D_t\) measures how consequential the decision is under exact minimax evaluation. A large value means that the available actions lead to substantially different future outcomes.

The normalized regret of the selected action is

\[
\mathcal R_t
=
\frac{
V_i^*(s_t)-Q_i^*(s_t,a_t)
}{
D_t
}.
\]

This quantity lies in \([0,1]\) when \(D_t>0\). Define \(\mathcal R_t=0\) when \(D_t=0\), because all legal actions are then equivalent under the evaluator.

These measures are for analysis and reporting. They are not additional training rewards.

Only valid generated game actions enter the regret, decision-spread, and optimal-action statistics. Reporting retains one diagnostic record per generated decision and uses the total number of valid decisions as the denominator; it does not average episode-level sums.

## 11. Experimental Design

The initial experiment should compare compute-matched training conditions, including:

1. the untrained base or instruction-tuned model;
2. terminal-outcome game training, in the style of SPIRAL;
3. the existing turn-level MARSHAL training condition; and
4. the proposed exact minimax-shaped training condition.

The comparison should control, as far as possible, for:

- the number of game trajectories;
- the number of generated and optimized tokens;
- optimizer steps and hyperparameters;
- opponent strength;
- starting-state distribution; and
- the amount of inference-time computation.

Evaluation should cover four levels:

### 11.1 Game Performance

- win, draw, and loss rates;
- exploitability or optimal-action rate;
- normalized regret \(\mathcal R_t\); and
- performance as a function of decision spread \(D_t\).

### 11.2 In-Game Reasoning

Analyze whether rollouts more often:

- enumerate plausible future actions;
- anticipate opponent responses;
- compare multiple continuations;
- revise an action after identifying a future threat; and
- maintain a coherent multi-step plan.

These behaviors require a clearly specified annotation protocol or an independently validated evaluator. They should not be inferred from a few selected examples.

### 11.3 Mathematical Transfer

Measure downstream mathematical accuracy and analyze whether the rollout changes observed in the game also appear in mathematics, for example through:

- considering alternative solution paths;
- checking future consequences of an intermediate step;
- detecting contradictions before committing to an answer; and
- revising a plan when a later implication fails.

### 11.4 Mechanism Tests

Useful ablations include:

- \(\delta=1\) versus \(\delta<1\);
- terminal reward only versus exact shaping;
- correct values versus shuffled or corrupted values; and
- training on optimal actions without reasoning text versus training complete reasoning-and-action turns.

The corrupted-value control is particularly important: if any dense reward produces the same transfer, the effect cannot be attributed specifically to future-consequence-aligned credit.

## 12. Intended Contribution and Limits

The novelty claim should not be that counterfactual credit or potential-based shaping is itself new. The intended contribution is a mechanism study:

1. derive a game-training signal from an intrinsic reasoning requirement of the game;
2. use an exactly solvable environment to make the decision-level signal unambiguous;
3. test how that signal changes the model's reasoning process; and
4. test whether the identified change transfers to another reasoning domain.

Tic-Tac-Toe is a clean proof-of-concept, not sufficient evidence for a general conclusion about games. A positive result would motivate extension to larger perfect-information games, where exact values can be replaced by search-based approximations. A negative result would also be informative: it would show that receiving future-consequence-aligned reward is not, by itself, enough to make an LLM internalize transferable lookahead.

The strongest defensible conclusion from the initial study is therefore conditional:

> If exact minimax-shaped game training produces measurable prospective reasoning in game rollouts, and the same change predicts controlled improvements in mathematical reasoning, then game environments provide evidence of being useful training grounds for a reusable thinking-ahead strategy.
