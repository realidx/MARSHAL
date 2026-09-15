# 4B B/P signal and full-game diagnostic

B 24 x 8 = 192; P 12 x 8 = 96; full games 12 x 4 = 48.
B groups: simple_exclusion6, maintain_pair4, fullset_control4, evidence_update6, complex_tendency4.
B train16/validation8; P train8/validation4. No test. Selection is deterministic coverage, not an unbiased accuracy sample or a fully paired contrast experiment. Existing validation simple formation exclusions have only want gold; refusal/avoid coverage also exists in updates. No new labels were created. Difficulty labels are provisional structural descriptors, not measured model difficulty.

Run `python -m training.social_mixed.probe --check` for offline rendering and scripted-game checks.
Run `python examples/social_mixed/a100_evaluate.py --probe --candidate MODEL --base MODEL --output NEW_DIRECTORY` with CUDA_VISIBLE_DEVICES set to the two allocated GPUs.

Two owned TP1 vLLM servers, CUDA graphs, max_num_seqs16 each; client semaphores limit active HTTP calls to16 per server. Both stages share the same loaded servers. Temperature1/top_p1/top_k-1/repetition1, max_tokens1024, context4096. B/P no retries; game protocol allows one retry with separately recorded -.1 cost. HTTP failure produces INCOMPLETE, not a game penalty. Successful collection marker counts attempts, not correct answers or completed terminal games.

The supplied internal JSONL includes labels/worlds. Only the native B/P renderer or Episode.request builds the HTTP messages/tools. Full game calls are flushed after every response. bp.jsonl contains raw requests, replies, usage and binary scores. games.jsonl contains terminal status, independent utility checks, protocol costs, original reset, and calls. game_calls preserves partial games. server logs contain vLLM initialization/runtime diagnostics.

Locally checked: 36 native B/P renderings; 12 scripted terminal games; all288 B/P and48 failure-path games through mocked HTTP with results flushed; actual4B tokenizer maximum sampled B/P prompt1773 tokens (plus1024 below4096). No GPU or real HTTP inference performed locally. All records are evaluation-only, not gradient-ready training data.
