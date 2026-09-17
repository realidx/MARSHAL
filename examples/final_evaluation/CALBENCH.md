# CalBench development integration

This is a plumbing check, not a formal transfer evaluation. Upstream source is
unchanged. `calbench_source.json` pins every source file by SHA-256; the runner
checks it before execution. The source snapshot was obtained from:
https://anonymous.4open.science/api/repo/calbench2026-235F/zip

The local copy is `third_party/calbench` (ignored like other third-party code).
Install with `python -m examples.final_evaluation.setup_calbench` or pass
`--archive /path/to/calbench-source.zip`. The installer validates individual
file hashes before installing and preserves any differing existing directory.
Preserve the downloaded snapshot when moving servers; a changed upstream release
must be audited and explicitly repinned. No private calendars or witness/oracle
solutions are passed to the model transport beyond native per-agent prompts.

## Development protocol

- 4 agents; 8 slots; 2 meetings with participants [0,1,2] then [1,2,3].
- Density 0.5, native 1..3 errand costs, prior-meeting cost 1.
- 2 cheap-talk sweeps per meeting, 1 decision retry, private DMs.
- `enable_fallback=false`: no algorithmic rescue of failed coordination.
- `enable_reflection=false`: no extra privacy-measurement LLM calls.
- Two concurrent games with the same world and focal seats 0 and 1. This is not
  a balanced formal test; the other seats and broader structures remain future work.
- All players use local Q0, 768 output tokens, temperature 0. No JSON-constrained
  decoding or prompt interventions are added; native parsing/JSON repair remains.
- The local launcher explicitly marks its two identical checkpoint replicas as
  equivalent; each game uses one replica. Separate per-agent histories are retained.
- External OpenAI-compatible APIs remain available through an explicit routes
  file with `local_only=false`; no provider detection or implicit cloud fallback.

## chenjiahao

Environment: `/raid/chenjiahao/mas/.venv-calbench`, fully isolated from the mas
training/inference environment. Create it and install dependencies with:

```bash
/raid/chenjiahao/conda_envs/mas/bin/python -m venv .venv-calbench
.venv-calbench/bin/python -m pip install -r examples/final_evaluation/calbench_requirements.txt
```

The vLLM servers use `/raid/chenjiahao/conda_envs/mas/bin/python`.

```bash
cd /raid/chenjiahao/mas
export CUDA_VISIBLE_DEVICES=6,7
export CUDA_HOME=/home/chenjiahao/cuda-11.8
export PATH="$CUDA_HOME/bin:$PATH"
export TRITON_PTXAS_PATH="$CUDA_HOME/bin/ptxas"
CALBENCH_RUN="$PWD/runs/calbench-dev-$(date +%Y%m%d-%H%M%S)"
nohup /raid/chenjiahao/conda_envs/mas/bin/python -u \
  -m examples.final_evaluation.launch_calbench_local \
  --output "$CALBENCH_RUN" > "${CALBENCH_RUN}.log" 2>&1 &
tail -f "${CALBENCH_RUN}.log"
```

Only use allocated free GPUs. The launcher starts its own services on ports
18105/18106 and removes only those processes on exit. A pre-existing server can
instead be used with `calbench_local --routes FILE --output NEW_DIR`.

Artifacts: native `trace.json`, incremental `events.jsonl`, per-agent transport
logs, private scenario (evaluator only), manifest, per-game `result.json`, combined
`games/results.json` and `games/RUN_FINISHED.json`. EXIT_CODE=0 means the harness
completed; inspect healthy_transport, batch_rejected, decision_failed,
invalid_tool_call and coordinated meeting counts separately. Failed scheduling
is a model outcome, not an infrastructure error. No formal score is claimed.

## Structural development suite (authored before Q0 results)

Run the same launcher with `--suite structures`. This runs two different cases,
all four agents using Q0; no focal model substitution. Each has one incoming
meeting, 4 agents, 8 slots, four cheap-talk sweeps and one decision retry. Only
three agents participate in the incoming meeting. Fallback and reflection stay
disabled. The earlier zero-cost smoke run is the basic-coordination control.

1. `cost_conflict`: feasible meeting slots are 0 and 1. At slot 0 agent 1 pays 8;
   at slot 1 agents 0 and 2 pay 3 and 1. No jointly free meeting slot exists.
   Native CP-SAT and native action replay both verify optimum 4 and alternative 8.
2. `prior_commitment`: a prior meeting 100 is already committed at slot 0 by
   agents 0/1/2. Incoming meeting participants are 1/2/3. Agent 3 has all other
   slots blocked. All three prior copies must move to their only common free
   destination, slot 1. Agent 0 must be contacted and act in the voluntary phase.
   This uses the native initial-prior-meeting representation, not a fabricated
   LLM conversation or a claim about decisions made in an earlier model round.

`python -m examples.final_evaluation.calbench_development_cases` verifies both
structures and runs four native replay checks: low/high cost choices, successful
external coordination, and failure without the external participant. These
scripted actions are validator-only and are never passed to evaluated models.

Oracle limitation: the native static solver returns 2 for `prior_commitment`,
missing external agent 0's required displacement. The verified team optimum is
3: three mandatory moves of unit cost, with a feasible native replay. Native
oracle-derived excess/normalized scores are therefore marked invalid for this
case. Use completion, raw team cost and the separately verified reference;
`verified_reference_excess_cost` is null if the meeting fails. Do not infer low
cost is good when scheduling failed. This is a development suite, not formal
CalBench leaderboard replication or a frozen transfer test.

## External-model rerun: 4096 tokens, unchanged prompts

User decision: rerun MARSHAL and Social-R1 only; retain Q0's original 768-token result.
Use `run_calbench_external_4096.sh marshal` or `socialr1` sequentially on GPU6/7.
The launcher accepts `--max-tokens 4096`, writes a separate execution protocol,
and extends HTTP timeout to 600 seconds to accommodate longer decoding. Native
prompts, temperature, context size, turns, frozen cases and costs are unchanged.
The previously diagnosed leading `<think>` parsing fix is included. Preserve all
prior runs; Q0 and these reruns differ in output budget and parser version.
