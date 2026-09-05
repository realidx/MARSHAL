# BENAC-P vLLM 0.28 trace

Slurm job `821875`, A100-40, seed `0`, 4 rounds, Qwen/Qwen3-4B-Instruct-2507,
vLLM `0.28.0`, Hermes tool-call parser, `max_tokens=4096`, temperature `0`.

- `episode.json`: clean final episode result and policy metrics.
- `trace.jsonl`: one normalized record per HTTP completion, including
  `usage.completion_tokens`, reasoning/content, tool calls, player, phase, and
  retry attempt.
- `job.stdout`: original job output.
- `server.log`: vLLM server log.
- `models.json`: `/v1/models` response.

The run contains 24 completion requests for 22 decisions, with two retries.
The mean API completion length is 1969.96 tokens; the final episode reaches
7/8 goals with rewards `[3, 1, 5]` and zero invalid actions.
