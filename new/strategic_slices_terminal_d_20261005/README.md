# Terminal D: full Qwen3-4B-Instruct-2507 results

The evaluation finished with 100 parents, 800 slices, and 6400 trajectories.
The original 16-worker job 910916 was explicitly cancelled after 58 complete
parents; continuation job 911072 reused those 3712 trajectories byte-for-byte
and evaluated the remaining 42 parents using 32 workers and completion-driven
refill. The continuation completed with exit code 0 in 27m55s.

## Results

- 10242 model calls: 10055 valid (98.174%), 139 truncated (1.357%),
  48 invalid actions/format failures (0.469%). No HTTP infrastructure failures.
- 6213/6400 terminal trajectories (97.078%); 139 truncation failures and
  48 invalid-action failures. Failure utilities are null, not game zeros.
- 657/800 slices have all eight terminal outcomes. Mean D among complete
  slices: train 0.509323 (413/504), validation 0.335949 (80/96),
  test 0.588479 (164/200). D is oracle value minus empirical utility.
- 78 training slices are complete and have observed root-value contrast;
  the diagnostic threshold of 100 is not met. No final 100-slice selection
  or model training was performed.

Raw reward variation includes independent hidden-world/reference draws. It
is not a GRPO active-group statistic. Eight repeats give coarse uncertainty.
The 58 inherited and 42 new parents use different execution schedules;
matching model/seeds does not guarantee token-identical outputs. Parent-level
protocol hashes and EXECUTION_MIGRATION.json retain that distinction.

## Files

- `summary.json`, `REPORT.md`: complete metrics and split/stratum summaries.
- `slices.jsonl`: all 800 slice measurements, failures and missing-outcome bounds.
- `train_signal_candidates.jsonl`: 78 train-only diagnostic candidates.
- `EXECUTION_MIGRATION.json`: both protocols and inherited parent checksums.
- `terminal-d-full-results.tar.gz`: both full run directories, including all
  parent trajectories, raw requests/responses, transport logs, server logs,
  runtime records, source snapshots and completion/failure evidence. The
  cancelled attempt's partial calls are retained for provenance and are not
  counted again in the final evaluation. No model weights are included.
- `ARCHIVE_MANIFEST.json`: archive SHA256 and every archived file hash.
- `slurm-original-910916.out`, `slurm-continuation-911072.out`: job stdout.

Extract into a new directory, then verify archive/file hashes against
ARCHIVE_MANIFEST.json. The final evaluation COMPLETE.json verifies its
protocol, summaries, all parent records and execution migration; all these
hashes were checked before packaging. Runtime absolute paths are provenance
records, not portable execution paths.

## Optimization

The old scheduler waited for an entire batch before sending another. The new
scheduler admits another ready trajectory after each completion, with at most
32 in-flight calls and at most one per trajectory. It preserves parent-atomic
results, independent seeds, context checks and transport-failure handling.
A tokenizer lock protects shared renderer state. Migration permits only
16-to-32/refill settings and the reviewed terminal_d source change; copied
parents retain their original protocol hashes.

Observed continuation KV peak was 60%, maximum running requests 32, and no
cache preemptions. Old job processed 58 parents in about 85 minutes; new job
processed 42 in about 28 minutes. Parent-rate improvement is approximately
2.2x, but the two cohorts differ and this is not a controlled benchmark.

Validation: eight original CPU checks plus two completion-refill/trajectory/
recovery tests passed under Python 3.10, and the HTTP context/transport check
passed after adding the tokenizer lock. Both inherited and final completion
hashes were independently verified.
