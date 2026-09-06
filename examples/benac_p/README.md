# BENAC-P menu diagnosis pilot

Run this on the remote GPU server. It follows the existing ItemGame HTTP
server setup and defaults to `Qwen/Qwen3-4B-Instruct-2507`. No ROLL/Ray is
needed for the diagnostic client. Use the project's Python environment
(with numpy); vLLM is needed only by the inference server.

```bash
# Terminal 1: existing repository server script; local model paths are supported.
VLLM_MODEL=/path/to/Qwen3-4B-Instruct-2507 \
VLLM_SERVED_MODEL_NAME=Qwen/Qwen3-4B-Instruct-2507 \
VLLM_MAX_MODEL_LEN=16384 \
bash examples/item_game/run_item_game_vllm_028_server.sh

# Terminal 2: exports oracle labels, sends 11 requests, and scores outputs.
bash examples/benac_p/run_menu_diagnose.sh
```

For an already running service:

```bash
BENAC_P_VLLM_BASE_URL=http://your-server:8000/v1 \
VLLM_SERVED_MODEL_NAME=your-served-model-id \
bash examples/benac_p/run_menu_diagnose.sh
```

`BENAC_P_VLLM_API_KEY` supplies authentication if required; it is not written
to artifacts. Other overrides: `PYTHON_BIN`, `BENAC_DIAGNOSE_OUTPUT_DIR`,
`BENAC_DIAGNOSE_MAX_TOKENS`. Use `--export-only` for a CPU-only oracle check.
Pass `--answers path/to/model_answers.json` to rescore saved answers.

Outputs in `runs/benac_menu_diagnose/<timestamp>/`:

- `tasks.json`: only model-visible inputs and output contracts.
- `oracle_labels.json`: separate exact posterior and Q labels, never sent to the model.
- `mechanism_certificate.json`: full menu/action comparison and negative controls.
- `model_answers.json`: incremental answers including raw model text.
- `scores.json`: validity, posterior TV/squared error, action regret, and paired interventions.
- `run_config.json`: model/server/token settings, excluding credentials.

The 11 requests are: a root choice with/without explicit current belief, then
three response branches, each with belief estimation and planning with/without
an oracle posterior. Oracle planning using model-estimated belief is scored
locally. This pilot isolates computations at fixed decisions; it does not
claim to identify independent internal neural modules. Root history/oracle
conditions contain the same initial information and are a prompt sanity check.
Invalid and missing outputs are reported, never silently replaced by PASS.

This **diagnostic probe** uses supplied legal action indices and JSON answers
so action serialization does not dominate the planning measurement. Normal
negotiation episodes use native `MENU`, `CHOOSE_1`, `CHOOSE_2` tools, enabled
with `python -m benac_p.cli --menu --self-play vllm --json`.

The fixture is intentionally tiny: three players, two scheduled ego turns,
five goals, an explicitly disclosed two-type prior over P1, and known P2.
It was selected by a search for a positive adaptive-planning gap and is a
mechanism test, not a representative benchmark. With future belief use the
optimal first action is a menu (value 1.673071); with frozen-prior continuation
the optimal first action is a single offer. The same-menu update gain is
0.166812. Both selected options yield immediate ego utility 1, but their
physical states differ. The update gain is relative to the defined frozen
policy, not a pure information causal effect. P2 provides alternative consent;
this example alone does not establish essential long-horizon multi-party
coordination. Known-type update gain is zero. The terminal-only control has
no opportunity for downstream information use.

Interpret the first remote run as a go/no-go pilot: check protocol validity,
then oracle-belief planning regret and model-belief/oracle-planner regret.
Before making a broad weakness claim, replicate on structurally distinct,
held-out instances and include useful/no-useful-information controls. No
LLM results have been pre-populated or inferred from the oracle certificate.
