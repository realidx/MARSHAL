# Structured v0 item game

The first item-game runtime uses one shared sequential engine and six
structural cases:

```yaml
custom_envs:
  item_game:
    env_type: item_game
    max_actions_per_traj: 6
    env_config:
      generator: mixed_incentive
      subtype: give_first
      max_ego_steps: 6
      communication_budget: 4
```

Available generator/subtype pairs are:

* `pure_collaboration / collaboration`
* `mixed_incentive / exchange`
* `mixed_incentive / give_first`
* `mixed_incentive / request_surplus`
* `resource_conflict / cannot_help`
* `resource_conflict / refuse_harmful_request`

Item labels are permuted deterministically from the episode seed.  The
partner is truthful and scripted.  Communication is hard-budgeted, all
nonterminal rewards are zero, and the terminal Ego reward is binary.

To run the Qwen-3-4B-Instruct pilot on a server, point `EVAL_MODEL_DIR` at a
local Hugging Face model directory containing `config.json`, then run from the
repository root:

```bash
export EVAL_MODEL_DIR=/path/to/Qwen3-4B-Instruct
bash examples/item_game/run_agentic_rollout_item_game.sh
```

The pilot is structured-answer only: `enable_think: false` and
`use_reason_answer_format: false`, so it does not require a `<reason>` tag.
Inference uses `max_new_tokens: 128` for one short structured action, not 1024;
the model context limit is 4096.  The environment accepts an optional reason
tag for protocol tests, but the pilot intentionally does not measure it.
