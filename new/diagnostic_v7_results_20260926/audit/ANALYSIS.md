# v7 Q0 / D24v1-step39 call audit

Data: bundled raw_runs.tar.gz, jobs881892/881891. Local manifest SHA matches supplied 0ae7b7247091d23c57f8a5f7983b77334337e375d701cd33e6c8947e9af5e9f6. Recomputed all256 saved B/action scores with current frozen scorer: exact match. This checks scorer replay, not an independent proof of teacher correctness. Service protocol explicitly enables batch invariance; no evidence here for attributing differences to the old batch issue.

## Main observation: belief-conditioned interfaces trigger investigation

| Model | O INVESTIGATE | P_gold INVESTIGATE | P_model INVESTIGATE |
|---|---:|---:|---:|
| Q0 |1|17|19|
| D |1|9|22|

All the P investigations are scored incorrect. For Q0,13/17 gold and15/19 model-belief investigations occur at the final proposal opportunity; for D,7/9 and19/22. Do not call all the others final-turn failures: they have two proposal opportunities remaining.

O-correct/P_gold-wrong: Q0 14 cases (8 initial-information controls,6 behavior); D8 (4/4). Reverse P_gold-correct/O-wrong:3 in each model. In the8 Q0 initial-information controls there was no behavioral history to remove in the first place. Missing history therefore cannot explain the entire gap. O/P differ in supplied judgment, objective wording, redundant initial-state display and call seed; these data do not isolate a causal prompt component.

Example interaction-43622c30a288d5d3de: Q0 O makes a correct Cedar/Maple offer. P_gold explicitly acknowledges that the game ends after this turn, yet investigates so it can choose an offer afterwards. Prompt explicitly states investigation consumes the current proposal opportunity. This is opportunity-cost/timing misuse, not lack of correct supplied B.

Example initial-03a06b6c8ef099da178a-B: correct belief has all3 possible, favored avoid. Q0 investigates; D passes after an extended contradictory analysis. D says the judgment means the hidden preference IS avoid. It also reads comma-separated jointly required commitments as alternatives, ignores already-binding commitments, and treats one disliked goal as a veto rather than summing gains/losses. Both O answers are scored correct but contain rule/state mistakes; correct action does not prove correct reasoning.

## Output failures are mostly grounding, not broken JSON

Recorded format_failure counts (O/P_gold/P_model): Q0 3/1/3; D2/3/2. All14 calls contain tool calls. Twelve put goal names (Harbor,Workshop,etc.) in commitment fields;2 request already-binding additions. These are semantic action/grounding errors grouped under format_failure, not transport outages. No truncation is recorded.

## D vs Q0 changes

O: lost7/gained3. P_gold: lost6/gained8. P_model: lost4/gained4. B: lost2/gained2.
B support-set exact:12/32→15/32; favored exact11/32→11/32; joint exact5/32→5/32. B-wrong/O-correct:17 cases Q0,14 D. These show metric distinctions, not proof of causal ability exchange.

Examples of O regression:
- initial-7518b4f473810638fe2a-B: D explicitly assigns -1 to an unmet WANT goal, although the rules state unmet goals give0, and rejects a beneficial offer.
- initial-7fc5c933a479a702d174-B: D maps Blair's Harbor commitment to Cedar instead of Maple.
- interaction-5643d23864d1448a8e: D avoids assigning the partner a useful commitment because of an avoided goal, rather than calculating the complete payoff tradeoff.
- interaction-efaa37ee4347e4cda4: D ultimately asks Blair to add already-binding Maple; the stored error is format_failure, not a valid suboptimal decision.
- Other losses include goal/player/commitment mismatches. Several Q0 successes also have unsound explanations, so these cannot automatically be called previously mastered knowledge that D forgot.

## Contract issue to test, not a proven sole cause

B requests explain possible_preferences and the >10 percentage-point favored rule. P insertion only says to use the inference output and lists the fields; it does not repeat their precise semantics. The example above treats favored as a certain/actual preference. Aligning the B/P semantic definitions is justified, but the effect must be measured with fixed cases and both checkpoints. It would be invalid to assume this alone explains all failures or to hint which game action is correct.

## Interpretation and next controlled check

The runs show rule grounding, summed-payoff/state reasoning, and uncertainty-triggered investigation mistakes. They do not isolate a pure B→P composition deficit or justify an assertion of parameter-level ability exchange. Likewise, unfavorable D scores do not on their own invalidate the diagnostic.

Preserve v7 results unchanged. For any revised prompt, freeze the same32 cases, tool schemas, teacher labels and server settings; explicitly define the supplied belief fields as in B and rerun both checkpoints. Report changed-input pairs separately from identical-belief pairs and separate opportunity-cost errors and semantic-invalid actions. Do not remove INVESTIGATE, force actions, pick new cases by model success, or relabel failures to improve D's score.
