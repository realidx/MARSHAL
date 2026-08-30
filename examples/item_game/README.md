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

For the five legacy subtypes, the state-changing Ego actions are:

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

Collaboration v2 uses a separate decentralized protocol:

```text
QUERY P1 GOAL | QUERY P1 HOLDINGS
INFORM P1 GOAL {...} | INFORM P1 HOLDINGS {...}
PROPOSE JOIN {EGO,P1}
ACT COMMIT {...}
```

P1 asks for missing Ego information before accepting or rejecting a proposal.
`ACT ACCEPT` forms the coalition but does not commit items; after Ego commits
its own holdings, P1 commits its own necessary items in the same transition.
Collaboration success requires the accepted coalition and the union of both
item-level commits to cover the shared goal.

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

To run only the new Collaboration v2 at larger scale, use the dedicated
Collaboration-only config. It defaults to 240 independent seeds and does not
schedule the other five item-game subtypes:

```bash
export EVAL_MODEL_DIR=/path/to/Qwen3-4B-Instruct
bash examples/item_game/run_agentic_rollout_item_game_collaboration.sh
```

The dedicated config uses `group_seed_base: 840000`, so episode `g` uses the
reproducible environment seed `840000 + g`. Change `rollout_batch_size`,
`env_groups`, and `n_groups` together if you want a different number of
distinct Collaboration scenarios.

## Test-only synchronous self-play v0

The synchronous self-play path is separate from the Ego-centric ROLL adapter.
It supports `collaboration`, `request_surplus_reroute`, and
`respond_to_give_request`; one shared model object drives P0 and every other
active player. Each round has a mandatory response phase followed by one
simultaneous decision phase. All decisions use the same round-start snapshot;
communications are delivered in the next round, while state actions are
resolved atomically. The environment performs no scripted social actions.

Decision answers use one short protocol action per line. The prompt exposes
general templates rather than a pre-enumerated legal-action table, and there
is no required `MESSAGE`/`ACTIONS` wrapper. For example:

```text
QUERY P1 FOR THEIR HOLDINGS
REQUEST TRANSFER {item_Q} FROM P1 TO P0
GIVE {item_M} TO P1
COMMIT {item_A,item_B}
```

The decision-phase templates are:

```text
QUERY <WHO> FOR THEIR <WHAT>
INFORM <WHO> MY <WHAT> IS/ARE <VALUE>
REQUEST TRANSFER <ITEMS> FROM <WHO> TO <WHO>
PROPOSE JOIN WITH <WHO>
GIVE <ITEMS> TO <WHO>
COMMIT <ITEMS>
```

The environment validates the filled-in template against the current snapshot.
Each active player may send at most one message (`QUERY`, `INFORM`, `REQUEST
TRANSFER`, `PROPOSE JOIN`, or no message) and zero or more state actions per
round. `COMMIT` is exclusive and public. A `GIVE` state action transfers the
sender's own unfrozen items immediately; it does not require a prior agreement.
Mandatory responses are batched by recipient and addressed by message id, for
example:

```text
RESPOND #12: INFORM P0 MY GOAL IS {item_A,item_B}
RESPOND #13: GIVE {item_Q} TO P0
RESPOND #14: REJECT
```

Response messages are free and do not consume the proactive communication
opportunity. `REQUEST TRANSFER` is a request, not an agreement: the requested
owner responds with `GIVE` or `REJECT`; an accepted `GIVE` transfers items in
that response transition. `PROPOSE JOIN` is the exception: it creates a
persistent agreement only after `ACCEPT`, and it does not commit holdings.
Coalition success is settled at episode end and requires every accepted
coalition member to have committed and the union of their committed
contributions to cover the shared goal.
The runtime uses `max_rounds: 6` and player ids `P0/P1/P2/P3`; `P0` is only
the evaluation focal player, not a privileged engine role.

With a local Hugging Face model directory, run a 30-episode pilot (10 per
subtype):

```bash
export EVAL_MODEL_DIR=/path/to/Qwen3-4B-Instruct
bash examples/item_game/run_item_game_self_play_pilot.sh
```

Results are written as JSONL trajectories containing per-agent observations,
private reasoning, response/decision actions, hidden ground truth for offline
analysis, terminal status, and per-player diagnostics. This mode is
evaluation-only and does not update model weights.
