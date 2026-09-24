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
