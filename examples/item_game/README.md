# Structured Item Coalition Game v0.3

The v0.3 runtime uses one shared sequential engine and six structural cases.
Each Ego turn is explicit: an incoming request is answered in a mandatory
response-only turn; Ego then chooses one autonomous ASK/SAY/ACT action; the
scripted partner responds or acts; and only then are holdings and commitments
updated.

```yaml
custom_envs:
  item_game:
    env_type: item_game
    max_actions_per_traj: 8
    env_config:
      generator: mixed_incentive
      subtype: give_first
      max_ego_steps: 8
      communication_budget: 6
```

Available generator/subtype pairs are:

* `pure_collaboration / collaboration`
* `mixed_incentive / exchange`
* `mixed_incentive / give_first`
* `mixed_incentive / request_surplus`
* `resource_conflict / cannot_help`
* `resource_conflict / refuse_harmful_request`

Item labels are permuted deterministically from the episode seed. The partner
is truthful and scripted. ASK/SAY communication is hard-budgeted, mandatory
responses to partner requests are free, all nonterminal rewards are zero, and
the terminal Ego reward is binary. Every generated instance is checked against
its subtype's mathematical invariants.

The only state-changing Ego actions are:

```text
ACT GIVE <item> TO <partner>
ACT JOIN_COMMIT <coalition>
```

`ASK GIVE`, `ASK EXCHANGE`, and `ASK JOIN` create an agreement only after an
explicit partner `AGREE` response. A partner-side `GIVE` is then executed
immediately in the same transition; the agreement itself does not transfer
holdings. `ASK JOIN` does not commit a coalition. Ego must fulfill Ego-side `GIVE` or
`JOIN_COMMIT`; partner-side actions are scripted and recorded separately. An
accepted but unfulfilled agreement makes terminal reward zero, even when the
goal is otherwise satisfied.

To run the Qwen-3-4B-Instruct pilot on a server, point `EVAL_MODEL_DIR` at a
local Hugging Face model directory containing `config.json`, then run from the
repository root:

```bash
export EVAL_MODEL_DIR=/path/to/Qwen3-4B-Instruct
bash examples/item_game/run_agentic_rollout_item_game.sh
```

The pilot uses structured answers with a bounded `<reason>...</reason>` scratchpad
and an exact `<answer>...</answer>` action envelope.  It uses
`max_new_tokens: 1024`, `sequence_length: 8192`, and vLLM
`max_model_len: 8192`; the per-decision answer is still stopped at
`</answer>`.
