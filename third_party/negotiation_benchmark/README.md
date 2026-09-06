# Negotiation benchmark (vendored)

This directory contains the negotiation benchmark used by the paper and the
mechanism-related additions from its anonymous artifact.

- Paper: <https://arxiv.org/abs/2603.14066>
- Public source: <https://github.com/dtak/negotiation_benchmark_public>
- Anonymous artifact: <https://anonymous.4open.science/r/negotiation_MARL-46B8/>

## Contents

`src/core/` contains the binding-commitment simulator, payoff calculation,
goal satisfaction, and exact/heuristic utilities. `src/methods/` contains
partner/offer selection methods, including the optional GNN estimator.

`src/rl/` contains the staged RL interface added from the anonymous artifact:

- stage 0: partner selection;
- stage 1: offer selection with an explicit no-deal action;
- padded observations and legality masks;
- PPO and reward-free exploration (RFE) training/evaluation helpers;
- held-out game generation and environment transition verification.

`games/` contains the document-grounded game JSON files and the fixed
balanced/adversarial 5-player bundle from the artifact. Model checkpoints and
notebooks are intentionally not vendored here because this project currently
uses the benchmark mechanism rather than reproducing the paper's experiments.

## Installation

```bash
pip install -r requirements.txt
```

The GNN estimator additionally requires `torch-geometric`; it is optional for
the simulator and staged RL environment.

## BENAC-P v0 game engine

### Diagnose step 1: computed facts and a controlled partner

Native LLM observations now include `grounding_version="state-facts-v1"`,
`current_state_facts` (ALL_OF satisfaction, missing commitments, own utility
contributions and utility if terminal), and `if_accepted` for a pending offer.
These are mechanical state facts, not future values or action recommendations.
Public views omit private utility values. The legacy ROLL payload is unchanged.

Run the seeded, private-information controlled baseline without an LLM:

```bash
PYTHONPATH=src python -m benac_p.cli --seed 0 --self-play controlled --json
PYTHONPATH=src python -m pytest -q tests/test_benac_p.py tests/test_benac_p_diagnose.py
```

`SoftProgressPolicy` is a Level-0 progress heuristic, not a rational oracle.
It scores OFFER/ACCEPT by the acting player's potential gain conditional on
acceptance and scores PASS/REJECT as zero. For completed fraction `f_g`, the
potential is `sum_g V_g * (S_g + w * (1-S_g) * f_g)`, with `w=0.5` except on
the last scheduled turn, where `w=0`. Probabilities are a softmax (temperature
`0.5`) mixed with `0.02` uniform noise. Partial progress does not change the
environment reward. No acceptance prediction or partner preference is used.

The `proposal_distribution(observation)` and
`response_distribution(observation, offer)` methods return `(action, probability)`
pairs without consuming randomness. `proposal_probability` and
`response_probability` expose the same likelihood used for sampling. The CLI
JSON records `controlled_policy` and `policy_seeds`; `specification()` provides
the public policy description without its random seed. Mixed LLM/controlled
diagnostics must supply that description explicitly; this smoke command runs
controlled policies only. Exact filtering and short-horizon Bayesian planning
are described below and in `new/diagnose_plan.md` at the workspace root.

### Diagnose step 2: conditional joint prior and exact filtering

`ConditionalPreferencePrior` enumerates the v0 preference distribution conditioned
on the ego's own preferences, each player having a WANT, and each goal having a
non-NEUTRAL player. It preserves correlations across goals and partners. Supply
the experiment's public `preference_probs` explicitly if they differ from
`(0.4, 0.2, 0.4)`. Additional hidden-state-based dataset filtering is not modeled.

`ExactBayesFilter(observation, prior=..., partner_policies=...)` starts from that
prior and replays only visible history. `synchronize(observation)` consumes new
completed events and a pending offer once, so the ego's responder belief includes
the proposal before choosing ACCEPT/REJECT. Ego actions are interventions, not
likelihood evidence. Direct `observe_proposal` / `observe_response` APIs support
streaming use. Partner kernels must currently be known `SoftProgressPolicy`
instances; their parameters are copied without using their random seeds.

The filter has a public shadow engine with dummy private values and rejects
inconsistent, stale or invalid/fallback histories. It neither reads true partner
preferences from full/debug views nor uses generator seeds. `belief` retains
joint hypotheses and normalized log probabilities; `to_dict()` includes the
joint distribution by default, with marginals and entropy as additional views.

```bash
# Default: 3 players, 3 goals, 2 commitments/player, 2 rounds; no LLM required.
PYTHONPATH=src python -m benac_p.belief_demo --seed 0 > /tmp/belief-step2.json
# Include the full joint distribution at every snapshot for detailed inspection.
PYTHONPATH=src python -m benac_p.belief_demo --seed 0 --include-joint
PYTHONPATH=src python -m pytest -q tests/test_benac_p_belief.py
```

The demo logs posterior marginals before responses and after completed turns,
per-action predictive likelihoods, public history and experiment specifications.
It verifies streaming against replay from the final observation. Exactness is
relative to the specified finite model, up to floating-point arithmetic. The
default enumeration guard is 100,000 raw candidates; the 8-goal configuration
requires 43,046,721 and raises `BeliefLimitError` rather than silently approximating.
This step provides inference only; it does not establish decision value, LLM
performance, or a Bayesian planning reference.

### Diagnose step 3: belief-conditioned terminal planning

`BayesPlanner.solve(observation, belief)` returns own terminal value and, at an
ego decision, all legal `action_values`, `optimal_actions`, and a deterministic
chosen `action`. `result.regret(action)` scores a legal ego action under exactly
that supplied belief. `act(observation, belief)` returns the action directly.
To evaluate an action selected under an estimated belief, score it using a
separate solve with the evaluator's correct posterior.

Ego nodes maximize utility; partner proposals and responses use known stochastic
`SoftProgressPolicy` kernels and update future beliefs. The update is shared
with the online filter. The root belief must already include the pending offer.
The planner never reads the original transcript, true partner preferences,
generator seed or metadata, and never reconstructs the prior. Only the current
sufficient public state, own preferences and supplied belief are used. It solves
best response to fixed partners, not a multi-player equilibrium.

```python
from benac_p import BayesPlanner, ExactBayesFilter

# observation is the ego's current legal private observation.
posterior = ExactBayesFilter(observation).belief
planner = BayesPlanner()
result = planner.solve(observation, posterior)
print(result.to_dict())
```

Optional `partner_policies={player_id: SoftProgressPolicy(...)}` must match the
filter/actual controlled partners. The default kernel parameters match step 1.
Search is complete to the actual terminal turn, with no discount, shaping or
truncated leaf evaluation. Defaults are at most 4 remaining proposer turns,
4096 hypotheses, and 50,000 expanded nodes. Exceeding any limit raises
`BayesPlannerLimitError`; no approximate/partial value is returned. Exactness is
relative to the specified finite model and floating-point arithmetic. Ties use
`tie_tolerance=1e-10`, preferring PASS/REJECT then legal enumeration order.

```bash
PYTHONPATH=src python -m benac_p.planner_demo > /tmp/planner-step3.json
PYTHONPATH=src python -m pytest -q tests/test_benac_p_bayes_planner.py
```

The demo constructs legal histories with identical current state but different
posteriors and optimal partners, plus a three-way goal requiring a later
partner's action to make an initial commitment valuable. These are constructed
verification fixtures, not evidence of LLM failure or population-level effects.
An independent contingent-policy enumeration test checks multi-step values
without invoking Bayesian updates or the planner under test. LLM diagnostics
and training remain subsequent work.

`src/benac_p/` is the policy-agnostic game implementation described in
`new/plan.md`. It keeps the original benchmark simulator intact while using
the v0 semantics needed by this project: private per-player preferences,
public transcript, binding commitments, atomic `PASS`/`OFFER`, and explicit
`ACCEPT`/`REJECT` responses.

Run a deterministic random-policy self-play smoke test from this directory:

```bash
PYTHONPATH=src python -m benac_p.cli --seed 0 --self-play random
PYTHONPATH=src python -m benac_p.cli --seed 0 --self-play oracle
PYTHONPATH=src pytest -q tests/test_benac_p.py
```

The oracle command uses exact perfect-information backward induction and is
intended for mechanism checks and controlled diagnostics. Its state budget is
configurable with `--max-solver-states`.

Generate the initial 100-game random self-play bundle and aggregate the
mechanism diagnostics:

```bash
PYTHONPATH=src python scripts/generate_benac_p_samples.py \
  --n-games 100 --output artifacts/benac_p_random_samples.json
```

The same runner accepts arbitrary `PlayerPolicy` implementations. For vLLM
self-play, the default backend talks to an OpenAI-compatible vLLM server, so
it also works with newer vLLM releases such as 0.28 without importing ROLL's
version-specific in-process wrappers:

```bash
# Start vLLM separately, for example with vLLM 0.28:
vllm serve Qwen/Qwen3-4B-Instruct-2507 \
  --served-model-name Qwen/Qwen3-4B-Instruct-2507 \
  --host 0.0.0.0 --port 8000 \
  --enable-auto-tool-choice \
  --tool-call-parser hermes

PYTHONPATH=src python -m benac_p.cli \
  --seed 0 --self-play vllm \
  --vllm-backend http \
  --vllm-base-url http://localhost:8000/v1 \
  --vllm-model Qwen/Qwen3-4B-Instruct-2507 \
  --json
```

The legacy ROLL in-process path remains available with
`--vllm-backend roll`; it requires a vLLM version supported by
`roll.third_party.vllm`. The canonical HTTP path sends native OpenAI tools
with `tool_choice="auto"` and `parallel_tool_calls=false`. Proposer turns
offer only `PASS`/`OFFER`; response turns offer only `ACCEPT`/`REJECT`.
`VLLMPlayerPolicy` allows ordinary text before exactly one tool call, retries
one missing/malformed/illegal call once, and records a final failure as
invalid rather than treating it as an intentional `PASS`.
With `--json`, the CLI also emits per-player `policy_metrics`, including raw
first-attempt validity and validity after the single retry.

## Using the existing vLLM interface

For an already initialized ROLL `LLM`/`AsyncLLM` (or an initialized
`VllmStrategy`), wrap it with the in-process benchmark adapter:

```python
from methods.vllm_client import VLLMNegotiationClient
from experiments.runner import run_single_game

llm_client = VLLMNegotiationClient(
    vllm_model,
    tokenizer=tokenizer,             # optional for sync LLM
    sampling_params=sampling_params,
    async_mode=False,                # True for AsyncLLM
)

result, _ = run_single_game(
    game_config=game_config,
    sat_masks=sat_masks,
    seed=0,
    method_config={
        "name": "vllm_llm_full",
        "how_fallback": "LLM_full",
        "llm_client": llm_client,
        "n_sims": 0,
        "c_ucb": 1.0,
        "use_prior": False,
        "max_changes": 2,
    },
)
```

The in-process adapter converts the benchmark's OpenAI-style messages into a
prompt and parses the legacy JSON envelope. For a vLLM server, use
`OpenAICompatibleNegotiationClient` from `methods.vllm_client`; native tool
calls are handled by `VLLMPlayerPolicy`. The benchmark remains responsible
for legal-partner, binding-action, forbidden-action, and action-budget
validation.

## Basic verification

From this directory:

```bash
PYTHONPATH=src python src/rl/verify_env.py
```

The verification script checks that the staged environment's partner choice,
no-deal transition, and accepted-offer transition agree with direct simulator
transitions.

## Scope note

The simulator keeps the paper's terminal payoff definition. In particular,
the anonymous artifact's additional per-committed-bit action cost is not
enabled here because its offer-delta calculations do not consistently account
for that cost.

### Binding menu diagnostic pilot

`--menu` enables two distinct legal offers to the same partner alongside
ordinary offers. The partner uses `CHOOSE_1`, `CHOOSE_2`, or `REJECT`; only
one selected commitment binds. Menus work with random, controlled and native
HTTP policies. The older perfect-information solver explicitly rejects this
mode; the known-partner `BayesPlanner` supports it.

From the repository root, run `bash examples/benac_p/run_menu_diagnose.sh`
on the remote inference server, or add `--export-only` for CPU validation.
See [the remote pilot instructions](../../examples/benac_p/README.md) for
server setup, outputs, exact controls and interpretation limits. This provides
11 fixed-decision probes and automated posterior/action-regret scoring.

The complete experiment is now `bash examples/benac_p/run_full_diagnose.sh`
(from repository root). It includes independent belief/planning probes,
belief × planner and chooser × updater interventions, controls, generated
and oracle-screened strata, and discovery/confirmation reporting. See
[the full protocol](../../new/full_diagnose_protocol.md). The menu command
above remains a smoke pilot, not the complete diagnostic experiment.
