# Partner32 evidence review

All 40 calls files audited; 32 tasks each have 20 sampled groups, eight responses/group. Each ten-update bin has 320 responses for each old domain, 160 each for new O/P views. The stored kind for new tasks is P in both views; classify by audited task ID suffix, not kind alone. This does not by itself prove incorrect loss routing.

|Training subset|0–9|10–19|20–29|30–39|
|---|---:|---:|---:|---:|
|Old O|233/320|269/320|286/320|276/320|
|Old B|155/320|220/320|284/320|306/320|
|Old P|140/320|171/320|213/320|219/320|
|New partner-choice O|78/160|125/160|136/160|135/160|
|New partner-choice P|96/160|126/160|133/160|144/160|

Old O truncations 7/14/17/33; old P 5/16/13/28; old B 67/46/14/4. O step20–29 versus30–39 legal/untruncated correctness is 286/303 vs276/287: aggregate fall accompanies increased truncation, not evidence by itself of semantic forgetting. Original v1 B labels remain full-set/undetermined, so B training accuracy does not establish nuanced belief inference.

CalBench D19→D39: final retained meetings33→38/72, full success4→7, optimal success2→5, slot mismatches33→29, realized team cost24→17 across24games. All four early successes retained. Added loose_uniform_s2, dense_uniform_s2, replan_uniform_s1. Thus this run's observed endpoints do not show later generalization degradation. Compared with original micro24 final47meetings/9success, current38/7 is worse. Different run, hardware and token budget prevent assigning the whole change causally to the added tasks. Response tokens2,438,815 versus1,782,494 (~37% more); original24 exposure remains20 each, not diluted to fewer visits.

ShapeFactory D19→D39: fulfilled1→0/12, average wealth190→188.75, no all-player success. D39 forward-dashboard: B proposes buying triangle from C, subsequently attempts to accept its own offer and fulfill an imagined delivered triangle. C first attempts to accept the buy offer before production; later produces triangles, but this game has no actual trade-response execution event. Repeated B rationale claims completed trade while native events show none. This is transaction-role/precondition/feedback grounding failure, not simply inability to identify a specialist.

Training counterpart: eight new views cover two terminal physical topologies and partner preference flips. They teach selecting an appropriate partner/commitment; they do not execute production→inventory→bidirectional transaction→fulfillment. Improvement on these training items establishes learnability, not mastery of a sequential economic workflow or new-structure transfer. The result rejects the simple explanation that adding learnable three-player partner choice alone is sufficient to fix ShapeFactory.

Both ShapeFactory checkpoint runs precede explicit output-budget v3.1 fix. Exit0/result availability alone do not establish clean provider/probe execution; avoid strong causal claims from four real-time games. Do not modify the environment/prompt to make this checkpoint score better. No training or evaluation settings changed during this analysis.
