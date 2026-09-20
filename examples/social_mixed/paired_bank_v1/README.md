# Paired O/B/P+ seed bank

Initial implementation, not a declaration that full-library pairing is complete.

Inventory covers all 742 train and 495 validation rows of v6. Expanded bank: **258 train and 239 validation canonical cases**, each with O/B/Pplus views (1,491 views). The original bank had 36 train and 71 validation cases. This covers actionable source cases, not every original B skill or every dataset row.

Native reconstruction audited 875 remaining source rows; 578 were actionable after revision 2 before deduplication. Across original P rows, 40 reconstructed acceptable-action lists differ from the supplied-belief labels: removing the supplied belief requires recomputing rewards. The replay and original labels are retained in `reconstruction.jsonl`; all included views passed exhaustive legal-action/B-answer interface roundtrips in two naming variants.

Excluded train rows: 124 terminal B histories, 48 other-player turns, and 20 cases with no action discrimination. Separately track 108 canonical duplicates, 36 oracle-view duplicates and 148 scaffolds. Validation excludes 97 terminal histories, 8 other-player turns, 80 canonical duplicates and 71 oracle-view duplicates. The previous 20 query-history cases and 19 state mismatches have been reconstructed with explicit revision-2 audit records; source files remain unchanged.

Rebuild with `python -m training.social_mixed.reconstruct_paired_bank` (resumable by exact source hash), then `python -m training.social_mixed.prepare_paired_bank`. Changing solver implementation requires deleting/archiving the reconstruction cache first; source hashes alone do not certify new solver code.

Canonical identity includes current native information and history, excluding supplied belief. O/Pplus share the exact action teacher and tool schema. Pplus appends the full same-information joint posterior and preserves the history. B preserves the source B query where available; other cases use a deterministically chosen partner-goal query (largest posterior uncertainty, index tie-break); its semantic answer is derived from that posterior, not used to approximate the Pplus joint belief. O has no supplied belief or inference-procedure instructions. Rules and partner-policy assumptions remain visible.

Original acceptable action scoring, including declared response tie conventions, is unchanged. It is teacher-policy-consistent action supervision, not a pure own-utility-tolerance reward claim. Seed cases use existing certified-history solver outputs; expanded cases use native replay and re-solved values; does not claim an independent new equilibrium proof.

## Arms

- `outcome`: O only.
- `decomposed`: O:B:Pplus loss weights 1:1:1.
- F/selfplay unchanged; C not implemented.

8 responses per question. Both arms target 9 effective groups/update: O 9, D 3 per view; at most 36 candidate groups. Common kernel/mode/information-role coverage sampling; independent active pools disabled. Actual accepted case distributions can still differ due to reward filtering. All generation counts against budget. Ratios are not token shares.

Paired development uses a fixed 24-case unassisted O panel stratified by kernel/mode from the 239 validation candidates, plus existing SP diagnostics. Both O/D choose best by mean raw O accuracy, strict improvement only. This is a new validation protocol and must start with step-zero evaluation; no cross-protocol curve splicing.

Entry configs and submit script accept outcome/decomposed. Bank hash is saved in experiment options and checked on resume. Existing whole-suite/preflight issues and GPU acceptance remain outstanding; this seed-bank implementation is not a recommendation to start a confirmatory full-budget run before expanding/reviewing coverage.

First claim remains whole training-package comparison (windows + fixed teacher scoring versus full SP), not pure start-state selection. O-D measures the explicit supervision package; without C it does not isolate B from Pplus assistance.


## Revision: native replay repairs and source supervision

Selection still follows the existing authored construction rules. No action-gap or VOI threshold is introduced. Revision 2 retries the 20 query-history rows and 19 state mismatches. All 39 reconstruct successfully before deduplication. Own INVESTIGATE choices are interventions, matching `prepare_reasoning_v4.query_followups`; partner actions remain likelihood evidence. Private answers must match the native query slots and condition the posterior. Repairs replace only stale duplicated binary/linear flags using the native game; changed dependencies or other state differences are rejected. Original v6 files are unchanged; each repair records before/after values.

For canonical cases first sourced from B, retain the authored query, kernel, skill and previous-belief context rather than replacing every B view with a new B1 question. Previous belief is supplied only in B, never O. Other source cases still use the existing deterministic query choice. Canonical deduplication can merge source tasks: the inventory records source kernel, skill and canonical mapping, so task counts must not be presented as complete original-skill coverage. Terminal/non-observer B histories remain outside the action-paired bank; moving them to another decision point would be a new construction.
