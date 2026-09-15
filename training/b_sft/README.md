# Social reasoning training and evaluation

Start with [SOCIAL_SERVER_RUN.md](SOCIAL_SERVER_RUN.md) for upload, vLLM startup, single-GPU and multi-GPU evaluation, and result downloads. [VLLM_SAME_CONDA.md](VLLM_SAME_CONDA.md) retains the environment installation/recovery notes.

The immediate objective is to exercise the generation, scoring, B-to-P handoff, retry and game-continuation logic before starting PPO. Resolve prompt/protocol ambiguity without requiring the base model to master the task. PPO remains the eventual training method: rewards from B's final judgments and P's final actions will train the generated reasoning and submissions. Explanations do not receive separate correctness labels. The existing B-only SFT trainer is a separate, older workflow; the current social B/P path has not yet been connected to the repository's PPO infrastructure.

## Current interface

- B answers every query determined by the initial public preference catalogues. It cannot substitute publicly known preferences for the required queries.
- P receives the model's validly structured B submission, including incorrect beliefs, and submits a complete legal action object. Invalid B submissions become an explicit unavailable status; their raw text and tool calls remain in the audit log.
- Both prompts are English and request an explanation before the tool call. Explanation presence is reported separately from answer correctness.
- The effective instructions and tool schemas are in [social_lm_eval.py](social_lm_eval.py); [social_presentation.py](social_presentation.py) renders public facts with explicit actors, goal labels, commitment meanings, and event provenance. The prompt version is `social-english-action-ids-v6`. MENU responses `CHOOSE_1` and `CHOOSE_2` select the first and second bundles. Unsatisfied goals contribute zero to every player's utility. The view distinguishes the current proposer turn from future turns and identifies OFFER versus MENU. The stage-specific system separates B inference from P utility maximization. Inputs begin with the task and decision, put known own preferences in a separate `own_preferences` object with an explicit `player` owner, and use named action IDs consistently in state, history, legal actions and tool arguments. Pending offers are explicitly awaiting a response and have not changed commitments. The parser requires an exact displayed legal object and maps it to the corresponding native action; binary vectors remain internal. Catalogue keys and B query player IDs identify the owner of each partner preference. Public partner rules preserve plan selection and tie-breaking; training runtime metadata is omitted. No teacher inference is added to these views.

B and P default to 1024 output tokens, including explanation and tool arguments, on both attempts. Each stage permits one retry for truncation, protocol failure, or a service error, with public failure feedback and no state transition. Valid but incorrect answers are scored without retry. Every attempt is retained; truncation, format failure and infrastructure failure are separate categories. `decisions.jsonl.supervision` keeps per-attempt task scores/masks separate from format scores/masks; unavailable task scores remain null. Legacy aggregate B accuracy still counts missing answers as errors and is not a combined training reward. P task scores here are reference regret, not PPO advantages. Only established format failures receive `format_score=-1`; truncated/service-error attempts have no format score. `truncation_score=-1` when the server reports `finish_reason=length`, and 0 for other model responses; infrastructure errors are masked. This is a cap-failure cost, not a claim of looping. There is no repetition detector or separate repetition penalty. B exhaustion yields unavailable beliefs; P exhaustion stops continuation without a fabricated payoff. Dataset distribution and the suitability of solver supervision must be reviewed before training.

The versioned scoring contract (`social-attempt-reward-v1`) is saved in `run_config.json.scoring_contract`. Each supervision row records `reward` and `reward_mask`: sum the available task, format and truncation scores with unit coefficients. A truncated attempt therefore receives -1 without a task label or additional format penalty; a format failure receives -1; a valid teacher-scored submission receives its task score. Infrastructure errors and valid submissions without an available task teacher have a masked reward, not zero success. Score both attempts independently: a successful retry does not erase the first failure, and the first failure is not added to the retry's reward. The eventual training consumer should apply each attempt's outcome reward to that attempt's generated reasoning and submission tokens; this evaluator does not implement token losses or PPO updates. The initial -1 cap cost is an explicit convention, not a tuned coefficient. No additional cost depends on reasoning length below the cap.

## Data and evaluation

Current packs are `new/local_data/social_generalization_v4` and the 14-point `new/local_data/social_smoke_v4`, relative to the repository root. They are development material, not a completed formal training or unseen-test release. The v3 packs remain frozen for reproduction.

For the generalization development pack:

| Cohort | Points | Selection |
|---|---:|---|
| `planning` | 68 | 52 nonterminal points, including 17 with informative B; 6 terminal ACCEPT and 6 REJECT controls, 2 MENU choices, 2 ties |
| `belief` | 55 | Diverse informative B cases plus no-exclusion controls |
| `both` | 110 unique | Shared points run once and contribute to both cohort summaries |

A combined fixed-point run makes 220 initial B/P requests (at most 440 including retries). The small verification pack makes 28 initial requests (at most 56 including retries): 6 informed planning points, 2 terminal ACCEPT, 2 terminal REJECT, 2 MENU choices, and 2 prior controls. Continuations add requests. With `both`, read the separate cohort distributions; the balanced terminal control contract applies to the planning cohort.

The pack's `questions.jsonl`, `B_evidence_questions.jsonl`, `all_candidates.jsonl`, `trajectories.jsonl`, `screening.jsonl`, and `summary.json` retain candidates, provenance, supervision masks, failures, and distributions. [social_dataset_v4.py](social_dataset_v4.py) extends the verified v3 pool with earlier decisions covering every native first action and explicit negative-payoff/MENU controls. Publication fails if informed planning, balanced terminal controls, or menu coverage is missing. New trajectories use the unchanged partner solver.

## Teacher and supervision

[shared_teacher.py](shared_teacher.py) defines the common partner mechanism. Each player acts using its own preferences and public history. Within the declared finite proposal window, it first maximizes its expected own utility, then other players' total expected utility on own-value ties, and finally uses native action order on residual ties. This is a declared policy assumption, not a claim about all rational partners or full-game optimality.

[online_social.py](online_social.py) defines the live interaction:

- Public setup actions and learner actions are interventions, not evidence for excluding partner types.
- After each learner action, the partner window restarts from the actual state and surviving worlds. Observed partner actions filter worlds using the declared policy.
- Unsupported histories and solver failures produce unavailable supervision. Exclusions that rely on residual native action order disable the local B score.
- Own terminal P utility is computed directly from the final commitments. Nonterminal P values describe reference-policy continuations; they are not the model's realized return or an on-policy advantage.
- Teacher labels remain outside model inputs. Wrong but well-formed B passes unchanged. Malformed B supplies an unavailable status, without raw B instructions or replacement by teacher B.

[online_social_audit.py](online_social_audit.py) checks native histories, terminal payoffs, reconstructed B supports, and action values. A matching replay verifies the declared mechanism; it does not establish that the mechanism is a universally appropriate social teacher.

## Running and reading results

From the repository root, a local pipeline check is:

```bash
PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
python -m training.b_sft.social_lm_eval \
  --data-dir new/local_data/social_smoke_v4 \
  --dry-run --cohort both --workers 2 \
  --p-rollouts 2048 --output-dir outputs/social_pipeline_check
```

Use a fresh output directory. This uses a scripted client, not an LM. Full server commands are maintained only in [SOCIAL_SERVER_RUN.md](SOCIAL_SERVER_RUN.md).

[social_smoke_audit.py](social_smoke_audit.py) joins each small case's visible facts, allowed partner types, per-type solver comparisons, and every action's complete native reference rollouts. It also exports exact request previews with an explicitly unavailable B in the P preview. `new/local_data/social_runs/social_smoke_v4_teacher_audit/` contains the local check: 14 points, 80 action values, 488 terminal rollouts, 28 partner events. These are teacher/prompt checks, not model results.

`--workers` runs independent points in separate processes. `--base-urls` assigns workers to model-service replicas. B then P and in-game turn order remain sequential. `--continue-game --roots-only` continues from selected roots; different roots can run concurrently.

Read `calls.jsonl` for exact requests, raw responses, explanations, token usage and latency; `decisions.jsonl` for scores and teacher comparisons; `episodes.jsonl` for actual continuation outcomes. The summary separates cohort, phase, terminal/reference value basis, informative B accuracy, protocol failures, explanation presence and teacher availability. Explanation presence and B passthrough do not establish reasoning correctness or causal use of B.

Run the relevant CPU regressions with:

```bash
PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
python -m unittest \
  training.b_sft.test_social_lm_eval training.b_sft.test_social_parallel \
  training.b_sft.test_online_social training.b_sft.test_social_dataset_v3 \
  training.b_sft.test_social_dataset_v4 \
  training.b_sft.test_shared_teacher training.b_sft.test_favored_belief
```

## Source layout and historical work

| Files | Purpose |
|---|---|
| `social_lm_eval.py`, `social_presentation.py`, `social_task.py` | Current model requests, public views, evaluation and fixed-query contract |
| `online_social*.py`, `shared_teacher*.py`, `favored_belief.py` | Native interaction, solver, supervision and audits |
| `social_dataset_v4.py`, `social_dataset_v3.py`, `social_cases*.py`, `social_holdout*.py` | Dataset construction and provenance; some older builders are still imported |
| `train.py`, `data.py`, `loss_backend.py`, `run_shared.sh`, `configs/` | Existing B-only SFT implementation and launch configuration |
| Other corpus/mining modules, `fixtures/`, `test_*.py` | Earlier experiments, reproducibility and regression coverage |

Keep new server runs under `outputs/` and downloaded runs under `new/local_data/social_runs/`. Existing `debug/` audit scripts and evidence are retained. Superseded notes, the previous README, and redundant intermediate dataset builds are preserved in [one archive](../../archive/training_cleanup_20260911.tar.gz), with original paths and a SHA-256 manifest. Historical SFT commands are in the archived README. Maintain these three current Markdown files rather than adding another progress note to this directory.
