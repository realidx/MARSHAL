# v4 training contract — discussion draft, 2026-10-06

**Historical draft, superseded by [TERMINAL_TRAINING.md](TERMINAL_TRAINING.md).**
The user accepted per-decision binary oracle correctness with shared resets.
The current implementation and local checks are described there; the utility
reward and failure alternatives below are not the active training contract.

**Original status: proposed choices, not an activated training configuration.** The 100
selected slices and frozen references are unchanged. No GPU task is submitted.

## Subsequent discussion: evidence and corrected status

The user has settled the training reset rule: replicas in a group share the
slice entrance, hidden world and focal player. The earlier reset-choice paragraph
below is historical discussion, not an open question. Different training groups
may sample new instances from the declared belief.

The earlier terminal-utility recommendation below is **not approved**. Old B/P
uses oracle correctness with binary task rewards; old self-play utility rewards
are a different recipe, not a reason to change the new slice objective by default.

An offline reward review now exists at
`new/local_data/strategic_slices_training_reward_review/binary_rescore.json`.
With numerical action-gap tolerance 1e-7, whole-window binary success is 179/800
selected trajectories: k=1 118/416, k=2 50/232, k=3 11/152. Strong acquisition
windows have only 2/96 whole-window successes, despite 9 optimal query choices
and 86/203 correct individual decisions. Only 48/100 questions showed both
binary outcomes in the eight stored samples. These are independent-reset D
observations, not effective-group estimates for shared-world training.

Current recommendation for discussion: retain oracle-correctness binary
feedback at each controlled decision, accept all value-tied optimal actions,
and use native terminal utility as the external outcome measure. Whole-window
binary success remains a useful evaluation metric but is empirically sparse.
Per-decision feedback is a different objective/credit-assignment choice from
one binary trajectory reward. Its aggregation, advantages and failure treatment
still need agreement; no implementation has been switched to it. The evidence
supports trying it, not a claim that it will train better. A tolerance of 0.1
must not be imported casually: several intended information gains are <0.1.

## Reusable training infrastructure

Historical run evidence: [BP/SP training chains](../../new/training_chain_evidence_20260921/README.md)
and [D24 job 881010](../../new/d24_partner32_evidence_20260926/README.md).
Reuse the ROLL optimizer, behavior-logprob audit, PPO clipping, reference KL,
weight synchronization, checkpoint/resume and token accounting in
`training/social_mixed/pipeline.py`. A successful older run does not establish
that the new terminal-slice collector or a larger sequence budget already works.

The current `training/strategic_slices/runtime.py` is not the desired contract:
its Collector zeroes every task advantage when any replica fails. The newer
`assign_sp_completed_advantages` in `training/social_mixed/reasoning_training.py`
retains completed-only task comparisons and separate failed-call penalties.
That newer behavior is the proposed starting point, not an instruction to reuse
the old slice collector unchanged.

## Proposed episode semantics

1. Sample a selected question and a compatible entrance/hidden world from its
   frozen joint distribution. Materialize the public history and focal player's
   private answers exactly as in D evaluation.
2. The model controls at most k **focal decisions**, including proposals,
   investigation and ACCEPT/REJECT responses. Partner actions do not consume k.
3. Every partner move uses the same saved initial terminal oracle profile.
   After k model decisions, the focal player also returns to that profile until
   native terminal. No new equilibrium is solved during rollout.
4. End early if native terminal is reached. k is a maximum, not a minimum.
   Only model-generated response tokens enter the policy loss; oracle actions
   and environment observations are not supervised model targets.
5. After each legal action, construct the next visible state as in D. Previous
   generated reasoning is not silently appended: changing the conversation
   format would be an additional experiment.

These semantics preserve the C/S/D window definition. Changing the model to
control every player, or stopping game scoring after k actions, would change
that definition.

## Main reward: proposed terminal utility

For a completed episode use the focal player's original native terminal
utility. Do not automatically award a bonus for INVESTIGATE, imitate one
oracle tie-break action, or substitute C/S/D for an episode reward.

Use completed trajectories' utilities to form within-group task advantages.
The initial proposal is the existing mean/std normalization. A completed
trajectory's task advantage is shared by its controlled calls. Equal trajectory
weight with an average across its calls matches the earlier production recipe,
but is a training weighting choice; it should not be described as exactly the
same objective as an unweighted sum of trajectory log-probabilities.

Per-step oracle Q gaps remain diagnostics in the first experiment. Turning them
into dense rewards changes the feedback supplied to the learner and needs a
separate declared treatment, even though they can be useful for analysis.

## Truncation and illegal output: two alternatives to decide

**Proposed baseline: separate task and protocol objectives.**

- On an output-token limit or an invalid/missing/multiple act call, stop that
  episode. Its native terminal utility is null; do not set it to zero or let
  the oracle silently repair/complete the failed action.
- Other completed replicas remain eligible for task comparisons. Do not zero
  the entire group. Fewer than two completed values, or identical completed
  values, yields zero task advantage for that group.
- The failed episode has no outcome-based task advantage, including its valid
  prefix; this avoids inventing a final outcome. Put the existing fixed -0.2
  protocol advantage only on the failed model call. All generated prefix and
  failed-response tokens still count against the token budget.
- A mixed complete/failed group still has a protocol-learning signal. It need
  not have a strategic task contrast. With exactly one completion there is no
  outcome-comparison advantage; this limitation is explicit.
- Even an all-failed group retains the independent protocol penalty. It is not
  silently classified as an active strategic-reward group.
- Transport errors, server failure and context overflow are infrastructure
  errors; stop/recover the job, not penalize the policy. No answer retry or
  automatic extension of a truncated response.

**Alternative: a scalar failed-episode penalty.** Give failed trajectories a
training score below every legal completion, then normalize all replicas
jointly. This directly ranks completion above failure but introduces a reward
scale, penalizes valid earlier decisions in the failed trajectory and changes
the objective. A game reward of zero is unsuitable because legal terminal
utilities can be negative. All-failed groups also need an explicit treatment;
normalizing identical failure scores alone produces zero advantage.

The alternatives are not interchangeable. Neither is enabled by this draft.

## Other decisions that should be explicit

- **Training group resets:** old slice training shared entrance/world within a
  group; D used independent resets per replica. Sharing a world reduces one
  source of within-group noise but is not an observed oracle label for that
  hidden world. Group normalization and partner randomness still affect the
  learning signal. Independent worlds preserve the question's belief sampling
  within each group but add reward noise. Decide this before freezing the
  collector; do not infer it from D's eight samples.
- **Sampling count:** eight was the D diagnostic budget; old slice training
  defaulted to four. Training replicas, temperature and group construction are
  separate choices, not already settled by D.
- **Token budget:** D used 4096 output tokens per call and 16384 context. The
  older training entry still sets 4096 total sequence length with its earlier
  response budget. Do not silently reduce the new data's output budget. A
  4096-output training profile requires compatible prompt/sequence limits and a
  GPU memory smoke test; D's serving memory settings do not establish training
  capacity. k does not multiply the token limit of an individual response.
- **Scheduling:** the D HTTP server's completion-refill implementation is not
  automatically interchangeable with native ROLL generation. Reuse native
  behavior tokens/logprobs and weight-version checks; audit concurrency on the
  actual training backend.
- **Evaluation:** use existing validation data without selecting on test; report
  terminal utility, completion, query-target quality and answer use separately.
  Strong acquisition held-out coverage and long-horizon transfer remain open.

## Work that can proceed after the choices are settled

Export an adapter for the selected 100 questions with references and separate
validation data; implement the agreed collector/reward contract behind a new
version; check k=1/2/3, early terminal, failures after a valid prefix, mixed and
all-failed groups, information isolation, oracle handoff and exact resume.
Then prepare a short native GPU update/checkpoint/reload smoke run for manual
submission. No new supervision-label corpus is required for this online RL
baseline: the model generates its own actions and receives the agreed reward.
