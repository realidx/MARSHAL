# Transfer implementation audit — 2026-09-26

Scope: current CalBench stream24 and CollabSim frozen three-player ShapeFactory, not retired fixed-clock adapters or Hidden Profile.

Sources: pinned `third_party/calbench` and `third_party/CollabSim` (08ed0ed1cefb2edf1ea389b20ba8355815a7c8d0), checked against their complete file hash manifests. Paper definitions: [CalBench §4.2](https://arxiv.org/html/2605.09823v3#S4.SS2), [CollabSim §4.2](https://arxiv.org/html/2606.06399v1#S4.SS2). Source verification establishes fidelity to these pinned snapshots, not to every upstream version.

## Findings and corrections

1. The native ShapeFactory Slurm launcher still selected historical **two-player** `shapefactory_lite`, despite the current formal protocol selecting **three-player** `collabsim_frozen_v3`. It now invokes the frozen entry with checkpoint provenance. This is an entry-path defect, not proof that prior three-player runs used two players: their generated configs remain authoritative.
2. ShapeFactory documented a 4096 output budget, but generated model configs omitted `max_tokens`. The native LiteLLM backend only forwards it when configured; the launcher's routes.json was not consumed by this runner. Set model.max_tokens=4096 explicitly. Old runs' effective cap depended on serving defaults; do not relabel them as equivalent without evidence.
3. ShapeFactory summary formerly exposed native `completed_trades`, which includes declined/cancelled offers. Frozen v3 postprocessing corrected it, but standalone summarization did not. One shared summarizer now reports `resolved_offers_native` and counts executed accept events separately. Both native JSON-array events and JSONL are supported.
4. Add original-paper agent-level full-order fulfillment, trade acceptance, and message/trade metrics. Preserve item completion and whole-team completion as distinct supplementary fields. No-trade message ratio is null; no-offer acceptance follows upstream analysis's zero convention with a zero-denominator flag. Missing/failed runs do not get survivor-only aggregates.
5. CalBench native `meetings_scheduled` counts coordinated round resolutions; local `final_valid_meetings` checks final retained consistency. These can differ. Preserve both, explicitly named. Add per-agent native success, positive excess cost, communication and fairness fields; privacy remains unmeasured. No change to engine outcomes, scenarios, prompts or score formula.

ShapeFactory revision is **v3.1**, with the original manifest retained as `manifest.pre_audit_v3.json`. Updating the cap can affect future trajectories; it is not a reporting-only change. The other metric additions do not change gameplay. Do not overwrite archived raw results.

## Intentional departures from the papers

- CalBench: authored frozen 24 scenarios, four homogeneous agents, eight slots, three sequential meetings, local cost levels and four communication turns; reflection disabled. Native prompts, JSON parsing, calendar actions, retries, atomic resolution and cost accounting are retained. Qwen leading `<think>` transport separation is explicit, with raw responses retained. This is a smaller homogeneous transfer suite, not a replication of the paper's 90-task mixed-team setting. Native composite privacy default is not measured privacy; do not call composite headline the paper score.
- ShapeFactory: three agents, three specialties, one non-specialty order each, two ring directions × private/dashboard. Native prompt/persona, action schema, observer visibility, controller, wall-clock scheduling, 30s production delay, 900s duration, no-op stopping and probes are retained. Dashboard removes peers' tasks and in_production: it is not full information. Four runs are not four independent task families.
- Native ShapeFactory runs can exceed 900s process wall time because in-flight actions/probes take time. Native behavior is not silently changed into fixed action quotas. Matched servers and per-run timing/call records remain necessary.

## Validation and remaining limits

Regression tests cover source integrity, native CalBench oracle/replan replay and final consistency, three-player self-supply and trade-ring economic replay, upstream ShapeFactory metric parity, refused/cancelled trades, zero denominators, missing runs, launcher routing, and explicit budget/configuration preservation. Economic replay executes the native task actions; it does not simulate 30s production timing. Four generated ShapeFactory configs pass the native schema, and frozen hashes verify.

No live GPU/model evaluation was launched. Offline tests cannot certify remote checkpoint identity, actual 96K service capacity, batch invariance, latency fairness, or absence of swallowed provider/probe failures. COMPLETE means process completion, not model success or a clean transport certificate. These limits must remain explicit; no claim of an error-free remote run is made.

Validation result: 20 tests passed in the full offline run; after extending launcher coverage, the seven launcher/stream-runner cases also passed (22 distinct tests in the resulting suite). Initial native replay attempts lacked opentelemetry in local Python; dependencies were installed into isolated /tmp/transfer-audit-deps and the actual native replays then passed. No upstream source was modified to bypass imports.
