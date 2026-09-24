# Corrected D training: live log snapshot

This is a snapshot of the ongoing fresh-start D run `878558`, not a final
training result. The source checkout was clean at commit
`e157e25dfa92709fc119039be5604cac4f411cd8`. The run uses the opt-in
interaction bank and the `interaction-v2-name-contract` static request/scorer
fix; `experiment.json` records `resume=null`.

`d0-35-878558.tar.gz` contains original per-update calls and units through
zero-based step 35, plus game records, 38 copied metrics entries, the Q0 and
step-20 validation and static-O monitoring records, probability warnings,
phase timings, resolved config, environment, topology, and training/Slurm logs.
Files were copied while training continued, so the root logs may extend
beyond the last complete per-step call file. No checkpoint weights or HF export
are included; only `checkpoint-19/COMPLETE.json` is preserved as a manifest.

SHA256: `831a0547080ae09806e41bf8e6c638e0503c733e8148700db6c42b2199343e8d`

## D-19 frozen CalBench

`calbench/d19-878627-h10047.tar.gz` preserves the complete H100-47 run
`d19-fixed-878558-h10047-biinv-v1-stream-878627`: 24 per-game result,
trace, event, and transport records; the overall result; frozen manifest;
execution protocol and identity; server/routing metadata; and the server log.
The separate `.out` and `.err` files are the original Slurm streams. Triton
compilation cache and model weights are excluded.

The run completed with exit code 0: 4/24 coordinated, 0/24 successful and
optimal, mean headline score 0.431491; 24/24 healthy transport, 23/24
untruncated, four strict envelope failures. These are results for the early
corrected-chain checkpoint-19, not the final training outcome.

SHA256:

```
43f51a04e5ed82c70215ef7537f5ee15168305433ab067f7acf49330ff3c1f5d  calbench/d19-878627-h10047.tar.gz
563bd3fd77308df427213ba0503ede06a2628c5417d131becf07aa550fe038a4  calbench/calbench-biinv-v1-878627.out
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  calbench/calbench-biinv-v1-878627.err
```
