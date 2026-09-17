"""One held-out native-tool test of a selected model; no optimizer or feedback."""
import argparse
import hashlib
import json
from pathlib import Path
from training.b_sft.social_bp_grpo import read, validate_tasks
from training.b_sft.social_bp_training import reward, summarize
from training.b_sft.social_b_grpo import parse_completion
from training.b_sft.social_named_probe import request


def main():
    p = argparse.ArgumentParser(); p.add_argument('--model', required=True); p.add_argument('--data', default='examples/social_bp/data/tasks.jsonl')
    p.add_argument('--out', required=True); p.add_argument('--seed', type=int, default=20260915)
    a = p.parse_args(); out = Path(a.out); out.mkdir(parents=True, exist_ok=False)
    tasks = read(a.data); validate_tasks(tasks); tasks = [t for t in tasks if t['split']=='test']; assert len(tasks)==64
    from transformers import AutoTokenizer
    from vllm import LLM, SamplingParams
    from vllm.entrypoints.openai.tool_parsers.hermes_tool_parser import Hermes2ProToolParser
    tokenizer = AutoTokenizer.from_pretrained(a.model, local_files_only=True)
    parser = Hermes2ProToolParser(tokenizer)
    requests = [request(t, 'action_tools', t['name_variant']) for t in tasks]
    prompts = [dict(prompt_token_ids=tokenizer.apply_chat_template(r['messages'], tools=r['tools'], tokenize=True, add_generation_prompt=True)) for r in requests]
    assert max(len(p['prompt_token_ids']) for p in prompts)<=4096
    llm = LLM(model=a.model, tensor_parallel_size=1, dtype='bfloat16', max_model_len=5120,
              gpu_memory_utilization=.8, enforce_eager=True, seed=a.seed)
    sampling = SamplingParams(n=8, temperature=.8, top_p=1., top_k=-1, max_tokens=1024, repetition_penalty=1., skip_special_tokens=False)
    records = []
    with (out/'samples.jsonl').open('w') as f:
        for start in range(0,len(tasks),8):
            outputs = llm.generate(prompts[start:start+8], sampling, use_tqdm=False)
            assert len(outputs)==len(tasks[start:start+8])
            for t, req, generated in zip(tasks[start:start+8], requests[start:start+8], outputs):
                assert len(generated.outputs)==8
                for sample in generated.outputs:
                    if sample.finish_reason not in ('stop','length'): raise RuntimeError('Incomplete test generation')
                    text = tokenizer.decode(sample.token_ids, skip_special_tokens=False)
                    completion = parse_completion(parser,text,req['tools'],truncated=sample.finish_reason=='length')
                    scored = reward(t,completion); records.append(dict(task=t,score=scored))
                    f.write(json.dumps(dict(task_id=t['id'],sample_index=sample.index,token_ids=list(sample.token_ids),raw_text=text,
                                            completion=completion,score=scored))+'\n'); f.flush()
            print(json.dumps(dict(completed=len(records),planned=512)),flush=True)
    report = dict(model=a.model, data_sha256=hashlib.sha256(Path(a.data).read_bytes()).hexdigest(),seed=a.seed,
                  samples=len(records), measurements=summarize(records), parameters_updated=False, curriculum_updated=False)
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__ == '__main__': main()
