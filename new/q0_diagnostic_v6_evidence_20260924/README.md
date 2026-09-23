# Q0 strengthened diagnostic v6 raw evidence

The standalone archive `q0-base-v6s-874333.tar.gz` is the complete run
directory for Slurm job 874333. It contains the frozen profile, server log,
`structure_v6/calls.jsonl`, `results.json`, `protocol.json`,
`summary.json`, and `COMPLETE.json`. The job exited 0 and returned all
96/96 planned structure replicas.

The model is the untrained Qwen3-4B-Instruct-2507 baseline. The recorded
model checkpoint hash is
`23b08e1e15c229a04999562e00966a2b295172e1398e01eadd250450e606193f`.
The diagnostic used the strengthened v6 code at commit
`2965091d4e1de1ee2d88c095ad87d71f6e49c270`, temperature 0,
three repeats, and `VLLM_BATCH_INVARIANT=1`. Its manifest and runtime
hashes match the D-53/D-72/D-148 v6 diagnostics in
`new/d_evidence_20260924/diagnostic/`, making Q0 the direct protocol
baseline for those comparisons.

Extract with `tar -xzf q0-base-v6s-874333.tar.gz -C DESTINATION`.
Verify the archive with `sha256sum -c SHA256SUMS`.
