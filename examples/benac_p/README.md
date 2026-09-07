# Native BENAC-P endgame diagnosis

The current entry point preserves native actions, rotating proposal turns and
independent player preferences, with active history-aware oracle partners.
Every P task includes public history; B→P pairs replace only the explicit partner
judgment in otherwise identical fresh contexts. Use a fresh output directory.

```bash
bash examples/benac_p/run_full_diagnose.sh
```

This selects legal short positions and runs B, P, B→P and P→B with the existing
remote vLLM/Hermes configuration. See [methodology and running instructions](../../new/native_endgame_diagnose.md)
for selection gates, oracle assumptions, outputs and a CPU validation command.
The default candidate budget may need expansion; incomplete selection stops
before model calls. No new native real-model results have been established yet.

---

# Archived semantic protocol (modified game)

The instructions below reproduce the previous restricted semantic experiment;
its results are not native-game results.

# BENAC-P complete semantic diagnosis

Use the existing remote vLLM 0.28 + hermes service. The client needs the
repository Python environment and numpy, without ROLL/Ray or a local GPU.

```bash
bash examples/benac_p/run_legacy_semantic_diagnose.sh
```

This now runs **semantic B, P given a judgment, B→P, P→B, and complete model
interaction trajectories**, using deterministic rational partners. The model
outputs only `SUBMIT_JUDGMENT(possible_preferences=[...])` or
`SUBMIT_ACTION(action_index=...)`, preceded by:

> Briefly reason about the task before submitting your answer.

No probability, utility, Q, ranking or plan output is requested. The default
`balanced` profile targets about **120 words for judgment and 240 for planning**,
without a sentence limit or mandatory minimum. It asks the model to stop after
a conclusion and to submit when actions tie. These targets are soft, not grading
criteria. The total completion cap remains **1024 tokens**,
including reasoning and tool arguments; auto tool calling is retained.

Defaults: `Qwen/Qwen3-4B-Instruct-2507`, `http://localhost:8000/v1`, four workers,
seed 20000. Use the same service/model environment variables as before:

```bash
BENAC_P_VLLM_BASE_URL=http://your-server:8000/v1 \
VLLM_SERVED_MODEL_NAME=your-served-model-id \
bash examples/benac_p/run_legacy_semantic_diagnose.sh
```

`BENAC_P_VLLM_API_KEY` supplies authentication and is not saved in artifacts.
Other overrides: `PYTHON_BIN`, `BENAC_DIAGNOSE_OUTPUT_DIR`,
`BENAC_DIAGNOSE_MAX_TOKENS`, `BENAC_DIAGNOSE_WORKERS`, `BENAC_DIAGNOSE_SEED`,
`BENAC_DIAGNOSE_GAMES` (an even number of matched bundles, at least two).

Default: **12 matched bundles / 36 games**. Every bundle contains unknown
relevant preferences, known preferences, and unknown irrelevant preferences.
Six bundles are discovery; six are confirmation. There are 288 static requests
and at most 504 additional requests; identical action/response branches are
reused across interventions. Exact counts and fingerprints are exported.

```bash
# CPU certification and task export; no model requests.
bash examples/benac_p/run_legacy_semantic_diagnose.sh --export-only

# Complete synthetic oracle test. Not a real-model result.
bash examples/benac_p/run_legacy_semantic_diagnose.sh --oracle-check

# Continue an interrupted run; keep all original parameters unchanged.
BENAC_DIAGNOSE_OUTPUT_DIR=/path/to/run bash examples/benac_p/run_legacy_semantic_diagnose.sh --resume

# Rescore saved model outputs without contacting the service.
BENAC_DIAGNOSE_OUTPUT_DIR=/path/to/run bash examples/benac_p/run_legacy_semantic_diagnose.sh --score-only
```

A normal invocation creates a fresh timestamped directory under
`runs/benac_semantic_diagnose/`. Do not reuse an old stochastic output directory.
`--response-protocol json_action` provides an action/judgment-only JSON control
in a separate output directory.

Read `report.md` and `summary.json` for the four blocks, both four-cell tables,
format coverage, matched controls and confidence intervals. `scores.json`
contains per-branch evidence/judgment measurements and both updater-repair
contrasts. `rollouts.json` contains all hidden-configuration trajectories,
commitments and terminal outcomes. `protocol_summary.json` reports completion
length, reasoning coverage and truncation; raw outputs remain in `answers.json`.
Invalid/truncated outputs are not strategic PASS actions. Incomplete branch
sets are not silently renormalized. Manifest and request hashes guard resume.

**Scope:** selected three-player, three-turn BENAC subgames with a public
stage-specific offer catalogue. Every proposal uses the original legal binding
commitment engine. Partners' terminal optimality is certified over all allowed
future ego choices using only their own preferences. This is not a population
estimate for unrestricted BENAC, a long-horizon benchmark, or transfer evidence.
All model-visible information needed for scoring, including equal-frequency
joint configurations and deterministic tie-breaking, is stated in the prompt.

Full definitions and caveats: [semantic diagnosis protocol](../../new/semantic_diagnose_protocol.md).

## Legacy experiments

- `run_stochastic_diagnose.sh`: previous four-block probability-output experiment.
  Its `--extended` probes remain available; they are not part of the semantic suite.
- `run_menu_diagnose.sh`: old 11-call menu-only pilot.
- [Old stochastic protocol](../../new/full_diagnose_protocol.md): historical metrics
  and interpretation; do not combine its results with the semantic suite.

The native unrestricted game runner remains available with
`python -m benac_p.cli --menu --self-play vllm --json`. It is separate from this
controlled diagnostic protocol and does not automatically use these certified
partner rules.


## Compare reasoning budgets before the next full run

The uploaded open-profile run had 105/584 truncated requests; downstream
planning accounted for 83/313. To compare accuracy and length on the same
inputs, use:

```bash
bash examples/benac_p/run_reasoning_calibration.sh \
  --source-run runs/benac_semantic_diagnose/retry-826767
```

This selects 72 discovery-only tasks balanced by condition, stage and role,
reuses their archived baseline, and makes **144 new requests**: compact
(80-word target) and balanced (120/240-word targets), both at the original
1024-token cap. Model judgments in planning inputs are frozen across profiles;
P is scored under the supplied judgment. No confirmation tasks are selected.
Use the same model weights and serving configuration as the baseline.

Read `report.md` / `comparison.json` under `runs/benac_reasoning_calibration/`.
The report compares completed-and-correct B/P rates, truncation and total
completion tokens. Its profile recommendation is provisional, not a guarantee
of noninferiority. `--export-only` performs local selection without inference;
set `BENAC_CALIBRATION_OUTPUT_DIR` and pass `--resume` to continue that same run.

After choosing the profile, freeze it for the full experiment in a fresh directory:

```bash
bash examples/benac_p/run_legacy_semantic_diagnose.sh --reasoning-profile balanced --seed 21000
```

`--reasoning-profile open` preserves the previous brevity instruction;
`--reasoning-profile compact` uses the 80-word target. Profile and prompt hashes
are recorded in the manifest; new profiles must not resume into old outputs.

For calibration 826995, test bounded final submission on the four balanced
truncations without rerunning its 68 completed answers:

```bash
bash examples/benac_p/run_finalization_calibration.sh \
  --source-run runs/benac_reasoning_calibration/826995
```

This makes at most four extra calls, each capped at 128 completion tokens, retains
both attempts and reports first-pass truncation separately from recovered accuracy.
Use `--export-only` to inspect the selected tasks without calls. To resume the output,
set `BENAC_FINALIZATION_OUTPUT_DIR` to that directory and pass `--resume`.
After verifying recovery on the actual server, run the complete diagnosis with:

```bash
bash examples/benac_p/run_legacy_semantic_diagnose.sh --reasoning-profile balanced --finalization-tokens 128
```

The main-suite default remains no recovery. See
[`new/semantic_diagnose_protocol.md`](../../new/semantic_diagnose_protocol.md) for
cost accounting and interpretation.

Investigate the B-interface issue in full run 827142 with a small discovery-only
wording × tool-availability comparison:

```bash
bash examples/benac_p/run_belief_interface_audit.sh \
  --source-run runs/benac_semantic_diagnose/full-balanced-final128-827142
```

Defaults to 10 fixed questions, with cached original-auto answers and normally
50 new requests (at most 60). Results separate known-copy, unresolved-prior and
evidence-update questions. `--export-only` makes no requests; set
`BENAC_BELIEF_AUDIT_OUTPUT_DIR` and use `--resume` to continue the same output.
See [`new/belief_interface_investigation.md`](../../new/belief_interface_investigation.md).

### Current full-run default: clarified episode prior

```bash
bash examples/benac_p/run_legacy_semantic_diagnose.sh
```

This now runs clear-auto B wording with explicit population/episode-prior semantics,
balanced reasoning, a 1024-token initial budget and 128-token finalization. Four
empty-history B checks run first; if all four are exact, the complete diagnosis
starts automatically. Otherwise the script stops and saves
`belief_preflight_answers.json` and `belief_preflight_summary.json`. Wrong checks
are not retried. Use a fresh output directory; the earlier no-recovery shell default
above is historical. The game, oracle, scoring and P prompt have not changed.
