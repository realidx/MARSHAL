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
