"""Single-GPU adapter smoke: native generation and reversible weight RPCs.

No gradient, optimizer, Ray cluster, model checkpoint, or training is created.
"""
import json
from pathlib import Path

import torch
import torch.distributed as dist
from vllm import SamplingParams
from vllm.entrypoints.openai.tool_parsers.hermes_tool_parser import Hermes2ProToolParser
from roll.third_party.vllm import LLM
from training.b_sft.social_b_grpo import parse_completion
from training.b_sft.social_b_rl import reward


def weight_roundtrip(worker):
    name, parameter = next((n, p) for n, p in worker.model_runner.model.named_parameters()
                           if n.endswith('norm.weight'))
    before = parameter.detach().clone()
    changed = before + 0.125
    try:
        worker.update_parameter(name, changed, [dist.get_rank()])
        assert torch.equal(parameter, changed), 'Weight RPC did not write parameter'
    finally:
        worker.update_parameter(name, before, [dist.get_rank()])
    assert torch.equal(parameter, before), 'Weight restoration failed'
    return name


def main():
    data = Path('new/local_data/social_runs/b_grpo_data_v1/train.jsonl')
    record = json.loads(data.read_text().splitlines()[0])
    model = LLM(resource_placement_groups=[{}],
                model='/raid/chenjiahao/mas/models/Qwen3-4B-Instruct-2507',
                distributed_executor_backend='uni', dtype='bfloat16',
                max_model_len=5120, gpu_memory_utilization=0.5,
                enforce_eager=True, enable_prefix_caching=False, enable_sleep_mode=False, seed=20260912)
    tokenizer = model.get_tokenizer()
    tools = json.loads(record['tools'])
    prompt = tokenizer.apply_chat_template(json.loads(record['messages']), tools=tools,
                                          tokenize=True, add_generation_prompt=True)
    params = SamplingParams(temperature=0.7, top_p=1.0, top_k=-1, max_tokens=1024)
    outputs = model.generate(prompt_token_ids=[prompt], sampling_params=params, use_tqdm=False)
    output = outputs[0].outputs[0]
    ids = list(output.token_ids)
    raw = tokenizer.decode(ids, skip_special_tokens=False)
    completion = parse_completion(Hermes2ProToolParser(tokenizer), raw, tools,
                                  truncated=output.finish_reason == 'length')
    scored = reward(json.loads(record['ground_truth']), completion)
    names = model.collective_rpc(weight_roundtrip)
    model.offload_states()
    model.load_states()
    # Dedicated inference cards retain the model through the offload/load hooks.
    after = model.generate(prompt_token_ids=[prompt],
                           sampling_params=SamplingParams(temperature=0, max_tokens=1), use_tqdm=False)
    assert after[0].outputs[0].token_ids
    result = dict(checkpoint=record['id'], token_ids=ids, raw_text=raw, reward=scored,
                  weight_rpc_parameters=names, resident_offload_cycle_generation=True,
                  note='Single-GPU smoke only; no gradient or distributed weight sync tested')
    Path('new/local_data/b_grpo_runtime/vllm_smoke.json').write_text(json.dumps(result, indent=2)+'\n')
    # Explicitly destroy NCCL groups before interpreter/CUDA allocator teardown.
    from vllm.distributed.parallel_state import cleanup_dist_env_and_memory
    del model
    cleanup_dist_env_and_memory()
    print('VLLM_SMOKE_COMPLETE', json.dumps(dict(reward=scored, weight_rpc_parameters=names)), flush=True)


if __name__ == '__main__':
    main()
