# Package A: fixed Q0 opponent audit

## Scope and validity

Sources: `runs/benac_a_soc/{q0-formal-859851,selfplay-step69-formal-859921,bp-step139-formal-859921,mixed-step59-formal-859921}`. All four runs contain 48 distinct scenario-seat records and normal runner completion. No infrastructure failures recorded. Every one of 192 episodes was replayed using the frozen native Episode transitions; validity flags, statuses, terminal utilities and protocol penalties agree with the saved results. Scenario resets and suite manifests match the local freeze. All arms share Q0 opponent file hashes, inference versions and evaluation script hashes. Initial requests match across arms; per-call native messages/tools/seeds, routing and sampling values were verified. Q0's focal and opponent hashes also match.

Configuration: temperature 1.0, top_p 1.0, 1024 output tokens, one retry. One model rollout per scenario-seat; 16 scenarios, ID spanning 3 geometries and OOD spanning 8. Do not interpret 48 seats as 48 independent structures. Models were chosen before A, but had already been examined on CalBench. Training budgets differ. Same-information teacher is not part of these results.

## Completion and conditional utility

Utility is the focal player's own native terminal utility. Means below exclude missing terminal outcomes, so MUST be read together with completion. This is not a complete-cohort scalar ranking.

| Model | Complete | ID complete | ID utility | OOD complete | OOD utility | Overall conditional utility |
|---|---:|---:|---:|---:|---:|---:|
| Q0 |44/48|22/24|0.288|22/24|0.068|0.178|
| SP step69 |38/48|20/24|0.525|18/24|-0.019|0.268|
| BP step139 |40/48|19/24|0.254|21/24|0.333|0.296|
| Mixed step59 |35/48|18/24|0.361|17/24|-0.245|0.067|

Binary/linear split (conditional own utility; terminal/12):

| Model | ID binary | ID linear | OOD binary | OOD linear |
|---|---|---|---|---|
|Q0|0.273 (11)|0.303 (11)|0.000 (12)|0.150 (10)|
|SP|0.800 (10)|0.250 (10)|-0.100 (10)|0.083 (8)|
|BP|0.400 (10)|0.093 (9)|0.182 (11)|0.500 (10)|
|Mixed|0.364 (11)|0.357 (7)|-0.625 (8)|0.093 (9)|

Observed signal: SP's strong stratum is ID binary; BP is more promising on OOD; Mixed's most pronounced deficit is OOD binary. These small selected completed subsets do not establish reliable population ranking or budget efficiency.

## Paired comparison and missingness

On matching scenario-seat pairs where both arms finish, Mixed minus SP averages -0.241 (29 pairs: 8 wins, 9 ties, 12 losses); Mixed minus BP -0.256 (30 pairs: 6 wins, 10 ties, 14 losses); Mixed minus Q0 -0.064 (34 pairs: 8 wins, 13 ties, 13 losses). Mixed-only / comparator-only completion counts are 6/9, 5/10, and 1/10 respectively. These paired survivor diagnostics do not remove selection bias.

Only 25 scenario-seat pairs finish under all four models. Their conditional means: Q0 0.080, SP 0.233, BP 0.253, Mixed 0.007. Mixed's pattern is not solely an artifact of using different sets of successful episodes, but this common subset remains selected. Conservative missing-utility bounds are recorded for every stratum in summary.json; no zero-imputation or significance claim.

## Failure attribution

| Model | Focal calls | Focal truncated calls | Other focal invalid calls | Games stopped by focal | Games stopped by Q0 opponents |
|---|---:|---:|---:|---:|---:|
|Q0|234|41|4|2|2|
|SP|189|25|2|5|5|
|BP|195|28|6|4|4|
|Mixed|177|0|22|10|3|

Truncations count calls, including recoverable first attempts; a final `invalid_action` game status may follow an earlier truncated call. Fixed Q0 is itself imperfect, and its failure frequency depends on the interaction history. Opponent errors remain part of observed system behavior, not infrastructure errors and not automatically the focal model's fault.

Mixed's 22 nontruncated invalid calls are all OFFERs: 16 include an already-bound commitment even though the tool expects only NEW commitments; 6 use goal names as commitment names. These are state/schema errors, not JSON syntax failure. Multiple retries repeat the same invalid offer. The problem should not be reduced to goal-vs-commitment names alone.

## Behavioral distribution

Among valid focal proposal decisions (excluding response decisions and invalid calls):

| Model | OFFER | INVESTIGATE | PASS | Total | Investigate fraction |
|---|---:|---:|---:|---:|---:|
|Q0|48|43|48|139|30.9%|
|SP|54|32|40|126|25.4%|
|BP|69|34|23|126|27.0%|
|Mixed|111|3|7|121|2.5%|

Mixed makes offers in 91.7% of these observed decisions. This is an action-distribution finding, not proof that the other models investigate optimally or that every Mixed offer is wrong. Histories and available opportunities differ by policy.

Mean focal output tokens: Q0 451.6, SP 501.7, BP 493.7, Mixed 58.2. Mixed includes nonempty content outside tool calls in only 11/177 focal calls (11/165 initial attempts); SP does so in all 189, BP 165/195, Q0 191/234. Output brevity is not evidence of an absence of internal reasoning. Paired with over-offering and state errors, it motivates investigating how Mixed's action/output policy changed during training rather than simply requesting longer explanations.

## Concrete strategically harmful action

`A-OOD-binary-2r-balanced-seat0`, Mixed:
- Alex avoids Orchard and Library; wants Harbor.
- Orchard requires Alex.Cedar + Blair.Maple.
- Harbor requires Blair.Maple + Casey.Maple.
- Library requires Alex.Maple + Blair.Maple + Casey.Cedar.
- First offer obtains Alex.Maple + Blair.Maple.
- At calls.jsonl line 5, Alex offers to add Alex.Cedar + Casey.Cedar; Casey accepts at line 6.
- Both avoided goals become completed, while wanted Harbor remains incomplete. Final own utility -2.

The action is perfectly legal and the episode completes. This directly demonstrates a problem beyond formatting: failure to account for shared commitments across wanted/avoided goals. No inference about hidden partner preferences is needed to recognize the two adverse goal completions.

Same scenario-seat: BP 0, SP 0, Q0 -1. Their textual explanations also sometimes misread goal requirements as partner preferences (for example treating “Blair.Maple is required” as “Blair wants this goal”). A correct-looking partner claim in natural language should not be taken as evidence of accurate belief inference.

## Next diagnostic priority

1. Audit Mixed's training trajectory: effective task advantages by B/P cell, reward/protocol/outcome contributions, response-length distribution, action mix, and changes around checkpoints. Current results identify behavior, not its training cause.
2. Trace whether data/scoring teach NEW-only commitments and all affected goal utilities, not merely target-goal completion. Review genuine legal but harmful actions separately from formatting mistakes.
3. Audit investigation value coverage and actual effective gradients. Mixed's very low query frequency is not evidence that the “unknown => investigate” bias was successfully solved.
4. Preserve this frozen run and current protocol. Any increased-token or grounding-assisted rerun is a separate controlled condition applied to every arm; do not overwrite this result or select higher-scoring seeds.

Files: `summary.json`, `invalid_call_evidence.json`, reproducible `analyze.py` (run from repository root as `python -m new.benac_a_audit_20260919.analyze`). This audit does not modify training, prompts, checkpoints or evaluation outcomes.
