# v4 D merge, full-window audit and 100-slice selection

The v4 panel now has real D evidence for all 800 candidates: 722 unchanged
questions reused from v2 and 78 from job 915300. All 6,400 original game records
retain their source archive/member/protocol checksums. No model run or training
was launched by this analysis.

| Scope | Questions | All 8 complete | Mixed completion | Root contrast | Any-step contrast | Added beyond root | Gap/completion contrast |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| train | 504 | 405 | 98 | 116 | 139 | 23 | 229 |
| validation | 96 | 80 | 16 | 21 | 23 | 2 | 42 |
| test | 200 | 164 | 36 | 63 | 68 | 5 | 99 |
| all | 800 | 649 | 150 | 200 | 230 | 30 | 370 |
| selected | 100 | 73 | 27 | 58 | 77 | 19 | 88 |


Selection: **100 train questions, 56 parents,
37 structural families**. All 12 strong acquisition
windows and all nine complete train entry-answer groups (27 member questions)
are protected. Test/validation outcomes are excluded from selection. Protection
preserves information contrasts; it does not assert every protected member has
within-question sampled contrast.

Actual distribution: `{"decision_kind": {"proposal": 54, "response": 46}, "k": {"1": 52, "2": 29, "3": 19}, "players": {"2": 54, "3": 46}}`.
Soft targets from train candidate metadata: `{"decision_kind": {"proposal": 54, "response": 46}, "k": {"1": 52, "2": 29, "3": 19}, "players": {"2": 54, "3": 46}}`.
Maximum four selected questions per parent and eight per family, except the
minimum required to retain protected groups: `{'bca1e1f1f06f2438108f': 9}`.
The recorded
optimization weights favor family/parent diversity and same-prompt value contrast;
D/C is a clipped ranking feature, including explicitly named completed-only D
for incomplete questions. These are transparent design choices, not a uniquely
optimal dataset or validated training recipe.

## Acquisition behavior

Across 96 trajectories from the 12 strong-S windows, the model executed
80 investigations: 9
had optimal finite-window action value and 71
were suboptimal investigation choices. This judges target choice against the
same saved terminal continuation; the oracle still optimizes only the focal k
controlled decisions.

The chosen query targets have information-status counts
`{'already_known_suboptimal': 71, 'uncertain_optimal': 9}`. "Already known" means the queried preference has
only one supported value in the model-visible information cell. Thus every
suboptimal investigation observed here asks for a preference that was already
inferable, rather than buying information about the uncertain preference. This
is a concrete input-reading/query-target error; executing INVESTIGATE by itself
does not demonstrate information gathering.

There were 93 valid subsequent model actions,
of which 24 had positive conditional
value gap. At actually visited public histories, only
6 calls had disjoint optimal action sets
across feasible answers to the model's query: 5
valid actions, 2 optimal, and
1 failed outputs. This small denominator
cannot establish reliable answer-use competence. It also shows why counting
INVESTIGATE alone is insufficient.

## Method and limits

Every recorded request, action, RNG reset and terminal path was independently
replayed with the frozen native reference, without equilibrium re-solving.
Only terminal payoff comparisons allow 1e-12 cross-platform floating-point
roundoff; actions, statuses, prompts and seeds match exactly. At each model
call the posterior uses entrance belief, fixed-reference action likelihoods,
and observed private answers. The model's controlled actions are interventions,
not hidden-world evidence. The remaining k-window optimal continuation supplies
all action values. All 9929 audited calls passed the check that identical
visible prompts within a question have identical Q vectors across replicas.

The sum of sampled decision gaps is a trajectory diagnostic, **not D or C/S**.
Primary D and its missing-outcome bounds retain the original definition. Failed
trajectories have null full-window loss/utility, with valid-prefix gaps kept
separately. Reward differences alone are not sufficient evidence because resets
and reference actions are stochastic. No minimum eight-completion rule is used
for selection, and no negative Monte Carlo D is silently clipped in the data.

The ten entry-answer groups are analyzed separately in REVIEW.json. Their
observed action values are weighted by the oracle group probabilities and use
valid actions only; missing outputs can bias this diagnostic. Collective S is
never copied onto an individual question. Strong acquisition held-out coverage
and long-horizon transfer remain unvalidated.

## Artifacts and reproduction

- `new/local_data/strategic_slices_terminal_d_v4_analysis`: merged D, question-level
  provenance, 100 parent replay audits, per-decision Q/posterior/gap, and checksums.
- `new/local_data/strategic_slices_terminal_selected_v4`: exactly 100 original
  candidate records, selected D/trajectory metrics, protected answer relations,
  selection rationale, reference hashes and checksums. References remain in v4.
- `new/local_data/strategic_slices_terminal_d_v4_review/REVIEW.json`: this report's
  detailed counts and entry-answer group measurements.

```bash
python -m examples.strategic_slices.analyze_terminal_d_v4
python -m examples.strategic_slices.select_terminal_d_v4
python -m examples.strategic_slices.report_terminal_d_v4
```

Use `--resume` for an interrupted unchanged audit; use fresh `--output` paths
for an independent rerun. These commands perform no model inference, job
submission, weight training or supervision generation. Four focused tests cover
native replay, hidden-world information isolation, later-step/failure signals,
and train-only protected-group selection.
