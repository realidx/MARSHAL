# Entry-set information contrast (2026-10-04)

The research definition remains S(Z) = optimal value with Z minus optimal value with Z masked, under the SAME reference profile, joint entrance/world distribution, native transitions and terminal utility. A particular channel is not a definition of all strategic information. No training labels or D are introduced here.

## Three explicit scopes

- `S_query`: access to a specified future private investigation answer inside k focal decisions. Existing implementation unchanged.
- `S_future_history`: future public transcript beyond retained physical observations and perfect recall. Existing single-root optional implementation.
- `S_entry_history`: a public-history contrast across a collection of first-focal-decision entrances with identical retained observations. Entrance evidence can differ while commitments, budgets, pending offer, legal menu, own type and private answers match. The implemented masking also excludes later extra public transcript; k=1 isolates the entry signal itself.

These channels may overlap and must not be added. Unmeasured channels are not zero. Threshold S > .05 is unchanged; mathematical positivity above numerical tolerance is recorded separately.

## Shared ex ante distribution

Let h index comparable entrances and w a hidden world. Store joint masses m(h,w) obtained from the SAME certified reference's actual prefix action likelihoods. Condition on the selected observation class once, not separately with equal weight for each history. Full policies distinguish h; restricted policies share actions at indistinguishable retained information sets. Partner policies remain their original full-history policies in both arms. Focal continuation after k also stays fixed, just as in existing C/S.

For a family of entrances, V_full = sum_h p(h) V*_h. A sequence-form LP maximizes restricted value, coupling decisions across matching observations and retaining previous own realization sequences. This preserves perfect recall. The implementation rejects multi-root inputs with earlier focal actions since the tree root and overlapping descendant trees. Thus it does not erase the player's own memory to manufacture information value.

C_span for the entry set is max expected terminal utility minus min expected terminal utility over full-information focal policies. Since the full policy can distinguish entry histories, it equals the probability-weighted mean of the member C_span values. Member C values, joint masses and group reach probability are retained. S belongs to this DISTRIBUTION OF ENTRANCES; it must not be copied to each realized entrance as an independently measured label.

These distributions differ from the earlier uniform/PASS-biased entrance pilot: those interventions have no type-dependent public likelihood. A shared exogenous prior must never be presented as a reference-conditioned posterior.

## Native calibration

`fixtures/public_history_information.json` and its reference NPZ contain native seed 2026100609, three players with one commitment each, three linear pair goals, 27 worlds, schedule B → A → C. The complete 6,971-node terminal tree was solved and certified from the initial state. The stored profile passes an independent complete deviation/tie certification again in the regression test.

At A's first proposal, compare B PASS with B proposing to C followed by C REJECT. All four histories have zero commitments, no used investigation budgets, no pending offer, the same A type and legal menu. Their conditional probabilities within this group are 1/3 for PASS and 2/9 for each of the three rejected offers. Group probability under the full reference is .084375.

At k=1, the full-information best choices are:

| Evidence | Best action | Expected terminal value |
|---|---|---:|
| B PASS | Ask B to commit, no new A commitment | 197/88 ≈ 2.238636 |
| B → C offer rejected | Offer A+C commitments | 2 |

Without the history distinction, the best common action is the first offer. Its value after a rejected B→C offer is 87/44 ≈ 1.977273. Thus

V_full = (1/3)(197/88) + (2/3)(2) = 183/88.
V_mask = (1/3)(197/88) + (2/3)(87/44) = 545/264.
S_entry = 1/66 ≈ .0151515.

There is no INVESTIGATE in these evidence histories or in the optimal k=1 focal actions. Query actions remain legal: the example does not remove native actions. The effect is conditional on this certified reference, which may have mixed/tied actions; no unique equilibrium claim. It is mathematically positive but BELOW the existing .05 screening threshold. Its whole-game probability-weighted contribution is smaller still.

The native test independently enumerates the one-decision action values using propagated terminal-reference payoffs and verifies E[max Q] − max E[Q] against the LP. Additional tests protect against weighting posteriors equally and forgetting prior focal actions. This establishes a real omitted information channel, not broad S-positive coverage.

## Candidate packaging

Use a separate entry-set review format, not the existing single-root training schema. Preserve full parent/reference provenance, all member histories and posterior weights, group reach, C and channel-specific S. Cap correlated k windows/entry sets per parent, split only by structural family, and list solver failures. D and training require an explicit entry-set sampling adapter and are not implemented by this calibration.

## Unified terminal candidate distribution format

`training.strategic_slices.terminal_candidates.TerminalCandidates` reads
`terminal-candidate-distributions-v1`. It is a review loader, separate from the
training `Dataset` contract. The package contains `parents.jsonl`,
`references.jsonl`, and `candidates.jsonl`.

Each candidate has one `reference_id`, focal `ego`, `k`, and a normalized joint
distribution over `members × worlds`. A single entrance uses exactly the same
schema with one member. `sample_member_world` samples this joint distribution;
it does not choose histories uniformly. C and V are weighted expectations of
member values; collective S remains on the candidate, never on each member.

Reference records preserve the actual native root history, background world
weights, complete certification and policy file/hash. Two belief regimes are
explicit:

- `initial-prior-plus-reference-reach`: solve the short parent from its initial
  state; member posteriors follow the saved reference's prefix likelihoods.
- `world-independent-public-prefix`: sample a legal, type-independent prefix of
  a longer parent, then solve its remaining native game. Condition own type and
  private answers at the member. This is not asserted to be the continuation
  of an initial-state equilibrium.

Named `information_channels` distinguish `query_answer`,
`future_public_history`, and `entry_and_future_public_history`. Null remains
unmeasured. The last channel retains the physical-observation/perfect-recall
mask described above. Query values retain their per-slot diagnostics. Channels
may overlap; neither their sum nor a separate S for every member is defined.

The unified builder rechecks selected late-root C/query S and computes future
public-history S for these selected records. This extra channel is a diagnostic
after source selection, not an exhaustive new selection pass. A final readback
rebuilds every selected reference to real terminal, verifies its policy hash,
replays member histories, and recomputes member C/V. Family splits and both caps
are enforced. The package remains `training_compatible=false`; no D, supervision
labels or model calls are produced by this workflow.

## Initial-oracle-consistent candidate contract

The active contract is `initial-terminal-oracle-consistent-v1`. Its target is
100 distinct parents with multiple candidate entrances/windows per parent;
100 final slices are selected only after a later D measurement. D is not run
by this build. The earlier unified package's exogenous-prefix parents do not
satisfy this contract and are not reused as qualifying references.

For each parent, build the complete native tree from its actual initial state,
including every legal action and all supported private worlds. Solve and
certify a single profile. The same profile supplies all prefix likelihoods,
partner actions, and focal continuation after k. An entrance is eligible only
if its information set has positive probability under this profile. If h is
the public action prefix and I is the focal's own type/private answer record,
the entrance joint mass is

`m(h,w,I) = prior(w) × product_t oracle(a_t | acting_player_information_t(w)) × 1[w compatible with I]`.

The posterior normalizes these masses. It is not reset to the prior. The
candidate selection threshold of 1e-10 applies to total information-set mass;
it does not smooth action probabilities or add reach to zero-probability
histories. An independent audit reconstructs the product along each saved
path, separately from the enumeration used for generation.

Sample from all positive-reach decision information sets within 1–3 remaining
proposal opportunities, including OFFER responses. Stratify by focal player,
remaining proposals, proposal/response kind, and focal's next proposal offset.
An offset of null means that focal has no proposal remaining but can still
respond. Cap the entrance pool before C/S measurement; retain every available
eligible (ego,k) pair before filling additional strata/entrances. This is
stratified, capped sampling, not exhaustive or probability-proportional yield.

`k` counts the focal's own proposal **and response** decisions; it is an upper
bound on control, not a promise that every branch reaches k. Store native-branch
minimum/maximum decision capacity and decision kinds separately. Capacity
includes all legal branches and is not an oracle-rollout probability estimate.
Compute C_k and each S_k over the whole contingent policy and native terminal
utility; neither sums per-step values. Channels remain distinct and unmeasured
ones remain null. Existing collective public-history calibration cases are
explicit auxiliary controls, not new independent signal mechanisms.

Parent identity is also checked modulo player/action/goal renaming while
retaining private type catalogues, normalized background weights, payoff
geometry and schedule. Renaming an existing game cannot satisfy the 100-parent
target. Each retained parent has one reference, multiple candidate windows,
and at least two distinct member histories. Family caps and split separation
remain in force; known calibration families remain train-only.

The solver contract remains own-utility epsilon-Nash plus local own-support
and response-only social-tie checks at the existing tolerances. The selected
profile may mix nonuniformly among remaining admissible ties. Its declared
off-path convention is not a formal sequential-equilibrium guarantee. No
alternate local equilibrium is silently substituted at an entrance.

## Existing private answers: one-decision entry contrasts (2026-10-05)

The original capped entrance sampler can omit useful decisions *after* an
investigation. `query_answer` measures the value of a future answer from a
pre-query entrance, whereas `entry_private_answer` measures using an answer
already available. The latter conditions on the historical investigation having
occurred; it does not establish that buying that investigation was optimal or
strictly better than acting immediately.

For one reachable public history h, focal type, selected observed query slot,
and values of all other observed slots, retain every positive-reach answer z.
The distribution p(z,w | h, own, other answers) comes from the original initial
oracle's full prefix likelihood. No uniform-answer resampling or prior reset
is allowed. All answers share the same legal action menu and per-world
continuation payoff table: choose the first action a, then use the frozen oracle
for everyone through native terminal. For k=1, write its conditional value as
Q(z,a). Then

`S_entry_answer = sum_z p(z) max_a Q(z,a) - max_a sum_z p(z) Q(z,a)`.

The restricted decision retains the complete public history (including the
focal's past actions), own preferences, and all other private answers. Only
the selected answer is unavailable to this one decision. The frozen
continuation can use that answer again after the decision, just as the existing
window S convention allows information use after k. This is a conditional
entrance-information comparison, not an alternate full-game equilibrium or
a policy that never received the answer throughout the past.

An epsilon=.1 `must-change` certificate additionally requires two answer
conditions to have disjoint own-utility acceptable-action sets. These are
conservative sets including all own-utility ties; response social tie-breaking
can only narrow them. S is computed with exact maximizing values, not by
summing acceptable-action gaps. Both the S>.05 and member C>.1 thresholds are
unchanged.

`audit_entry_answers.py` scans all reachable answer groups in the same 1–3
remaining-proposal neighborhood, bypassing the old 24-entry preselection.
`retain_entry_answer_contrasts.py` keeps one complete strong group per eligible
parent, ranking by original reach probability times S, then S and stable ID.
It retains all answer members, minimizes replacements, and preserves existing
player/k/decision-kind coverage and collective controls within the eight-question
cap. New singleton C values and posteriors are checked independently; a masked
dynamic program checks each selected group's S.

Each answer condition remains a separate, fixed-information question with its
own visible private answer. The relation's S is stored once in
`entry_answer_relations.jsonl`; it is never copied into member S fields. The
loader rejects incomplete relations or values inconsistent with their members.
This preserves the distinction between 800 questions and a smaller number of
collective information contrasts. The historical paper-bank calibration uses
balanced condition pairs only as a diagnostic: it cannot supply native reach
weights and is not counted as new oracle-consistent data.

## Early-round investigation audit

`audit_early_investigation.py` checks each player's first proposal in every
saved parent. It includes all positive-reach public histories and own-type
information cells (mass threshold 1e-10), even when more than three proposal
turns remain. It uses no C threshold, 24-entrance cap, or model outcomes.
Earlier responses by that player remain part of the public history.

Partners retain the original certified initial profile. The focal player
optimizes every remaining proposal and response to native terminal via a
complete best-response dynamic program, with counterfactual own reach and
the native information partitions. Two distinct quantities are recorded:

* `delta_investigate = max Q(INVESTIGATE) - max Q(non-INVESTIGATE)`. After the
  first action, the focal can optimize freely, including investigating later.
* `query_access_value = V_full - V_no_own_queries`. The second strategy class
  prohibits the focal from investigating at **all** future decisions. It still
  observes offers/responses and retains all other native observations. Partners
  can investigate and follow their unchanged reference policies.

Both comparisons change action availability, so a positive value can include
effects of the visible investigation event on partner continuation. It does
not by itself certify private-answer value. A positive case must also be checked
by preserving the query action/cost/public event and masking only the selected
answer through terminal, using `masked_answer_value`. Record both its optimized
S and the full-versus-masked value with that query action forced.

Neither metric is the already-known-answer S, nor does either change the
dataset's existing S labels. Query-access value zero means that some contingent
strategy without any own investigation attains the same expected utility
against this fixed partner profile. It does not mean every non-query action is
optimal, that the focal needs no inference, or that investigation is useless in
other parents or under other partner profiles.

The audit verifies that first-proposal cell masses sum to one per parent/player
and that full best-response values match the certified reference at reachable
entrances. It separately reports how much action Q changes from reoptimizing
the continuation. Analytic tests cover genuinely beneficial investigation and
prevent hidden-world clairvoyance; a native fixture checks the full-tree dynamic
program against independent entrance-wise terminal best responses.

```sh
python -m examples.strategic_slices.audit_early_investigation --output NEW_AUDIT_DIRECTORY
```
