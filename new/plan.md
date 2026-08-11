# Procedural DAG Vertex Geography Experiment

## Research objective

Use procedurally generated, exactly solvable games to test whether game post-training learns a reusable lookahead procedure rather than a fixed state-to-action policy. A fresh labelled DAG is generated for each episode, and evaluation separates IID performance from relabelling, depth, size, and topology generalization.

This first implementation establishes the environment, exact counterfactual signal, diagnostics, and preflight suites. It does **not** establish reasoning transfer; that claim requires later mechanism and non-game transfer experiments.

## Frozen v1 game specification

- Deterministic, two-player, zero-sum, perfect information.
- The game graph is a finite directed acyclic graph and every node is reachable from the root.
- The complete labelled adjacency list is visible to both players.
- A token starts at the root. Players alternately move it along one outgoing edge.
- A player whose turn begins at a node with no outgoing edge loses.
- Node labels and adjacency order are randomized independently of graph structure.
- The game-step discount is \(\delta=1\).

For a node/state \(s\),

\[
V(s)=
\begin{cases}
-1,&\mathcal A(s)=\varnothing,\\
\max_{a\in\mathcal A(s)}Q(s,a),&\text{otherwise},
\end{cases}
\]

and

\[
Q(s,a)=-V(T(s,a)).
\]

The decision-local game reward for a valid action is

\[
r_t^{\mathrm{game}}
=Q(s_t,a_t)-\frac{1}{|\mathcal A(s_t)|}
\sum_{a\in\mathcal A(s_t)}Q(s_t,a).
\]

Auxiliary interface controls remain separate:

\[
r_t^{\mathrm{train}}
=r_t^{\mathrm{game}}+r_t^{\mathrm{format}}+r_t^{\mathrm{length}}.
\]

The environment's `rewards` field contains only the selected game-training signal (centered \(Q\) credit or the terminal-outcome control). Canonical terminal utility is recorded separately, and the rollout manager adds format and length controls outside both signals. Artificial truncation or invalid output is not a legal game transition and has zero game reward and zero canonical utility.

With \(\delta=1\), values distinguish outcome-preserving decisions only. They do not prefer faster wins or slower losses. For diagnostics, `optimal_distance` uses a deterministic convention: terminal distance is zero, and a nonterminal node uses one plus the minimum distance among value-optimal children.

## Generator controls and strata

The generator exposes:

```text
num_nodes
min_depth
max_depth
min_branching
max_branching
transposition_rate
target_root_value
target_root_informative
target_root_optimal_distance
target_root_branching
target_informative_fraction
```

An informative node has

\[
D(s)=\max_a Q(s,a)-\min_a Q(s,a)>0.
\]

Candidates are scored against requested properties rather than accepted by a single narrow rejection rule. Each graph records its achieved root value, informative fraction, longest depth, branching statistics, and transposition rate so later sampling can explicitly balance:

| Dimension | Strata |
|---|---|
| Root value | winning / losing |
| Decision type | all actions equal / mixed values |
| Depth | shallow / medium / deep |
| Topology | tree-like / high transposition |
| Branching | low / high |

## Implementation phases

| Phase | Deliverable | Gate/status |
|---|---|---|
| 1 | Frozen specification in this file | complete |
| 2 | Immutable graph/state and exact reverse-topological solver | implemented; core checks pass |
| 3 | Seeded stratified DAG generator and relabelling | implemented; 100-seed/property sweeps pass |
| 4 | MARSHAL `GeographyEnv`, parser, opponents, registry | implemented; full dependency integration pending |
| 5 | Generic `counterfactual_*` diagnostics with temporary `minimax_*` compatibility aliases | implemented; legacy metric tests pass |
| 6 | Solver/environment correctness tests | implemented; dependency-light execution passes |
| 7 | Three-group root-decision rollout pilot | implemented; model run not started |
| 8 | Training configuration derived from Tic-Tac-Toe | smoke/control configs staged; blocked on model preflight |
| 9 | Smoke test, reward comparison, OOD evaluation, full run | future experiment |

## Correctness gate

No model training may begin until tests verify:

1. Generated graphs are acyclic and root-reachable.
2. Generation is deterministic for a fixed seed.
3. Every transition follows a declared edge.
4. The player to act at a terminal node loses.
5. Solver values satisfy the Bellman equations and \(Q(s,a)=-V(s')\).
6. Optimal actions have zero regret.
7. Uniform-baseline counterfactual rewards sum to zero over legal actions.
8. Relabelling preserves values and optimal actions up to the label permutation.
9. Invalid output leaves graph state and canonical values unchanged.
10. Random play terminates within the longest root-to-terminal depth.
11. Optimal-versus-optimal play agrees exactly with the solved root value.
12. Graph suite seeds/splits are reproducible and disjoint.

## Rollout-first pilot

Before any RL, run one deliberately small edge-of-competence experiment. It
contains three held-out graph groups rather than a large factorial pool:

| Group | Nodes | Root branching | Root optimal distance | Target transposition |
|---|---:|---:|---:|---:|
| Distance-1 | 12 | 2 | 1 | 0.15 |
| Distance-3 | 12 | 2 | 3 | 0.15 |
| Distance-5 | 12 | 2 | 5 | 0.15 |

Sample 10 graph seeds in each group and generate 32 independent stochastic
responses for each identical graph prompt: 30 graphs and 960 responses total.
With the default pipeline seed of 42, the 30 effective group seeds are the
fixed sequence 700042--700071; distinct environment seed namespaces keep the
three groups disjoint from one another and from the default training namespace.
The model sees the complete graph, current node, legal moves, rules, and output
schema. The `<reason>` field remains free-form and has no numerical budget or
reasoning schema. The prompt does not prescribe lookahead, backward induction,
or exhaustive analysis, because doing so would leak the hypothesized strategy
and can encourage semantic reasoning loops. It adopts only MARSHAL's instruction
to keep the thinking process concise. Generation stops at `</answer>` or at the
1,200-token hard ceiling.

The three groups use the same node count, root branching, generator depth
bounds, and target transposition rate. They differ in the exact shortest
optimal-continuation distance from the root. This isolates that solver-defined
depth proxy from the graph-size and root-branching effects observed in the first
pilot; it does not by itself prove how much lookahead a model actually used. No
budget-aware wording or two-stage answer extraction is used.

Each rollout evaluates only the root decision. The graph remains solved by
backward induction, so the selected move has an exact optimality label and
exact continuation outcome, but neither the root value nor any solver result is
shown to the model. Pilot generation targets an informative root with at least
one optimal and one suboptimal legal action, so pass@k cannot be made trivial by
an all-actions-equal root. No retry, format reward, length reward, optimizer, or model
update is used in this pilot.

Report final-root-move pass@1, pass@8, and pass@32 separately for each group,
averaged across graphs using the standard repeated-sampling estimator. Also
report validity and token-cap rates. Preserve raw responses for later manual
inspection. Root-state-value and process-certificate scoring are deferred; a
free-form explanation has no trustworthy automatic process label yet.

The executable configuration is
`examples/geography/agentic_rollout_geography_root_pilot.yaml`. Its results
determine whether a useful edge-of-competence region exists before the training
distribution and reward comparison are frozen.

## Training comparison (after gates pass)

Hold the model, optimizer, rollout budget, prompt, and graph distribution fixed:

| Training signal | Claim tested |
|---|---|
| No training | Base-model reference |
| Terminal result only | Whether ordinary game training is sufficient |
| Exact centered \(Q\) reward | Whether local alternative comparison improves learning |

Initial training keeps Qwen3-4B-Instruct-2507, REINFORCE, full-weight updates,
`seq-mean-token-mean`, and Markovian turn context. Because the game is impartial,
the current-state prompt omits arbitrary Player 1/Player 2 role labels; both
self-play roles still generate training decisions for the shared policy. The original smoke run
disabled retries and length shaping; it produced frequent 1,200-token
truncations. The next controlled arm retains the same game reward and adds only
MARSHAL-style format and conciseness controls. A full run is allowed only after
a 20-step smoke test preserves validity, strategic accuracy, diagnostic
records, and reward separation.

## Distance-3/5 counterfactual and MARSHAL stabilization arm

The game signal remains exact local counterfactual credit. It does not include
the MARSHAL episode return or a process reward. Those remain later, matched
experimental arms. After the original smoke run's length collapse, the current
stabilization arm adds MARSHAL-style auxiliary format and conciseness controls.

Training uses full-game self-play from informative Distance-3 and Distance-5
roots in equal proportion. At Distance-3, four procedural strata cross node
count (10 or 14) with low or high decision branching; Distance-5 similarly
crosses node count (14 or 18) with low or high branching. Low-branching roots
have two actions with graph branching capped at two, while high-branching roots
have three actions with graph branching capped at four. The transposition target
is held at 0.2 so planning distance, node count, and branching remain
interpretable. Each of the eight strata receives four of the 32 rollout groups.
Labels, row order, successor order, and episode graphs remain procedural. Group
size is one, so training does not generate repeated samples of the same prompt
as the preflight did.

The initial schedule is:

| Stage | Updates | Rollout decisions/update | Purpose |
|---|---:|---:|---|
| Smoke | 20 | 8 | runtime, reward separation, and logging correctness |
| Full learning run, checkpoint 1 | 100 | 32 | test sustained held-out Distance-3/5 learning |
| Full learning run, checkpoint 2 | 200 total | 32 | test stability and later transfer |

Responses retain the free-form reason/answer protocol and a 1,024-token hard
ceiling. There is no retry. Invalid or truncated output has zero game reward and
a separate format penalty of -1.5. A completed legal response receives a +0.05
format reward and a MARSHAL-style conciseness reward that decreases linearly
from +0.5 at 11 tokens to zero at 600 tokens; invalid, illegal, and truncated
responses cannot earn either positive reward. Full games are capped at eight
legal moves, covering the Distance-5 generators' maximum depth of seven.

Validation has disjoint fixed namespaces and no auxiliary penalties. It covers
Distance-1 sanity, Distance-3 IID, identical Distance-3 roots under the other
internal player identity, paired relabelled copies of Distance-3 IID,
topology/size-OOD Distance-3, and held-out Distance-5. Full-game evaluation is
deferred to a separate exact-solver evaluation so variable-length player
rollouts cannot crowd controlled root suites out of the validation batch. Online
diagnostics report unique graph seeds and, for every observed optimal distance,
decision count, validity, conditional optimality, and end-to-end optimality.

The executable configurations are:

```text
examples/geography/agentic_train_geography_counterfactual_distance3_smoke_2gpu.yaml
examples/geography/agentic_train_geography_counterfactual_distance3_2gpu.yaml
examples/geography/agentic_train_geography_counterfactual_distance3_5_2gpu.yaml
```

## Claim-to-evidence boundary

| Claim | Required evidence | Current status |
|---|---|---|
| The environment implements exact DAG Geography | correctness tests | focused suite passes; full runtime preflight pending |
| Counterfactual credit improves game learning | compute-matched terminal-reward control | future experiment |
| The model learns planning rather than labels | relabelling and procedural held-out graphs | future experiment |
| The model learns depth-generalizing lookahead | depth-conditioned OOD curve | future experiment |
| Game learning transfers outside games | mechanism-matched non-game evaluation | out of scope for v1 implementation |
