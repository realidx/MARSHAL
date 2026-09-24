# D continuation and D-52 CalBench evidence

This bundle preserves the original logs of D continuation job `878181` and its
frozen 24-game CalBench evaluation job `878528`. No native or HF model weights
are included.

- Training source commit: `da0e67050ffa6e5a8832e08fa41940deccd1e7b1` (clean checkout).
- Training data manifest SHA256: `730f0d819b3a9e48cbcdc781b17cd5db580317d569f196ae0b97f2fb66e0729d`.
- Training run: `decomposed-seed42-878181`. The archive contains per-update
  metrics, calls, units, game records, validation and O monitoring, resolved
  configuration, topology, and exit information. The Slurm output and
  checkpoint completion manifest are separate files.
- Final native checkpoint: `checkpoint-52`; its `COMPLETE.json` lists 18 files.
  The actual checkpoint/optimizer files are deliberately excluded from Git.
- CalBench run: `d52-878181-h200-biinv-v1-stream-878528`. The archive contains
  all 24 game results, traces, events, transport logs, protocol and execution
  metadata, server log, and exit information. Triton compilation cache is excluded.
- Frozen evaluation profile: H200, `VLLM_BATCH_INVARIANT=1`,
  `max_num_seqs=32`, `parallel_games=8`, prefix caching on, chunked prefill off,
  eager execution.
- CalBench: 6/24 coordinated, 3/24 successful and optimal, mean headline
  score 0.486188; 24/24 healthy transport, 22/24 untruncated, 2 strict
  envelope failures. The two truncated games must not be silently interpreted
  as ordinary decision failures.

SHA256:

```
ca324fcdb9a5e779268577797d53a7338f414575b637367540f3d6a20955ece2  training/checkpoint-52-COMPLETE.json
b4115054b50b1bb3fc530a52dac49ed6f3890ed0aa10b1d7a756d31f4df63644  training/d52-878181.tar.gz
39553cf0caa257c92a202e094d404bf3195ee11c2b353e953a6ec929df7d2648  training/slurm-social-decomposed-resume-h10047-878181.out
10cc24956db590325bd962a87c6c312a6ca89239ca9c38cc29835c1a37269b68  calbench/d52-878528.tar.gz
```
