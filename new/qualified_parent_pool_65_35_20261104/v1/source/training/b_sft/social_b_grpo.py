"""Native-tool adapters for the repository's existing ROLL GRPO pipeline."""
import argparse
import json
from pathlib import Path
from training.b_sft.social_b_evaluation import request, PROMPT_VERSION, require_current_tasks
from training.b_sft.social_b_rl import CONTRACT, reward, read, dump, jsonl, digest
from training.b_sft.social_b_training_data import single_queries, VERSION as CURRICULUM_VERSION


def validate_export(folder):
    """Fail before optimizer startup on stale or mixed-query curriculum exports."""
    from training.b_sft.social_b_training_data import select_batch
    folder=Path(folder); manifest=json.loads((folder/'manifest.json').read_text())
    if manifest.get('training_unit')!='single_query' or manifest.get('curriculum_version')!=CURRICULUM_VERSION:
        raise ValueError('Re-export the audited single-query behavior curriculum')
    families={}
    for split in ('train','validation','test'):
        path=folder/(split+'.jsonl')
        if digest(path)!=manifest['files_sha256'][path.name]: raise ValueError('Export changed after verification')
        rows=read(path)
        if not rows: raise ValueError('Empty split')
        teachers=[json.loads(r['ground_truth']) for r in rows]
        if len({r['id'] for r in rows})!=len(rows): raise ValueError('Duplicate checkpoint IDs')
        for t in teachers:
            if t.get('training_unit')!='single_query' or len(t['input']['queries'])!=1 or len(t['gold']['judgments'])!=1:
                raise ValueError('Multiple queries in optimizer data')
            if families.setdefault(t['family'],split)!=split: raise ValueError('Family leakage')
        if split=='train':
            for step in range(60): select_batch(teachers,step,60,4,20260912)
    return manifest


def parse_completion(parser, text, tools, *, truncated=False):
    """Use vLLM's native Hermes parser; never recover JSON from prose."""
    try:
        from vllm.entrypoints.openai.chat_completion.protocol import ChatCompletionRequest
    except ModuleNotFoundError as exc:
        # vLLM <=0.8 exposed this request model one level higher.
        if not (exc.name or "").startswith("vllm.entrypoints.openai.chat_completion"):
            raise
        from vllm.entrypoints.openai.protocol import ChatCompletionRequest
    request_kwargs = dict(model='social-base', messages=[dict(role='user', content='')])
    if tools:
        request_kwargs['tools'] = tools
        request_kwargs['tool_choice'] = 'auto'
    req = ChatCompletionRequest(**request_kwargs)
    extracted=parser.extract_tool_calls(text,request=req)
    message=dict(role='assistant',content=extracted.content,
                 tool_calls=[c.model_dump() for c in extracted.tool_calls])
    return dict(raw_message=message,finish_reason='length' if truncated else 'stop')


def export(data_dir, output_dir, model):
    from transformers import AutoTokenizer
    try:
        from vllm.tool_parsers.hermes_tool_parser import Hermes2ProToolParser
    except ModuleNotFoundError as exc:
        if not (exc.name or "").startswith("vllm.tool_parsers"):
            raise
        from vllm.entrypoints.openai.tool_parsers.hermes_tool_parser import Hermes2ProToolParser
    tokenizer=AutoTokenizer.from_pretrained(model,local_files_only=True)
    parser=Hermes2ProToolParser(tokenizer)
    data=Path(data_dir);out=Path(output_dir);out.mkdir(parents=True,exist_ok=False)
    tasks=[q for t in read(data/'tasks.jsonl') for q in single_queries(t)]
    pairs=read(data/'pairs.jsonl');families={}
    require_current_tasks(tasks)
    if any(t.get('curriculum') for t in tasks):
        summary=json.loads((data/'summary.json').read_text())
        if summary.get('version')!=CURRICULUM_VERSION or not summary.get('training_ready'):
            raise ValueError('Curriculum data audit has not passed')
        if any(digest(data/name)!=summary.get('data_sha256',{}).get(name)
               for name in ('tasks.jsonl','pairs.jsonl','contrasts.jsonl')):
            raise ValueError('Curriculum data changed after teacher audit')
    for t in tasks:
        if t['family'] in families and families[t['family']]!=t['split']:raise ValueError('Family leakage')
        families[t['family']]=t['split']
    longest=0;split_sizes={}
    for split in ('train','validation','test'):
        records=[]
        for t in tasks:
            if t['split']!=split:continue
            r=request(t)
            text=tokenizer.apply_chat_template(r['messages'],tools=r['tools'],tokenize=False,add_generation_prompt=True)
            ids=tokenizer(text,add_special_tokens=False)['input_ids']
            direct=tokenizer.apply_chat_template(r['messages'],tools=r['tools'],tokenize=True,add_generation_prompt=True)
            if ids!=direct:raise ValueError('Native prompt token mismatch')
            longest=max(longest,len(ids))
            if len(ids)>4096:raise ValueError('Prompt budget exceeded; no silent truncation')
            # Verify parser/gold/schema round-trip for every exported query set.
            tool_text='<tool_call>\n'+json.dumps(dict(name='SUBMIT_BELIEFS',arguments=t['gold']))+'\n</tool_call>'
            if reward(t,parse_completion(parser,tool_text,r['tools']))['reward']!=1:raise ValueError('Native parser roundtrip failed')
            if reward(t,parse_completion(parser,'SUBMIT_BELIEFS('+json.dumps(t['gold'])+')',r['tools']))['reward']!=-1:
                raise ValueError('Parser accepted ordinary prose')
            categories=t.get('category_queries', [dict(category=p['category'],query=p['query']) for p in pairs
                if p['after']==t.get('parent_checkpoint',t['id']) and p['query'] in t['input']['queries']])
            teacher=dict(id=t['id'],family=t['family'],input=dict(queries=t['input']['queries']),gold=t['gold'],
                tools=r['tools'],category_queries=categories,training_unit='single_query',
                curriculum=t.get('curriculum'))
            records.append(dict(id=t['id'],messages=json.dumps(r['messages']),tools=json.dumps(r['tools']),
                ground_truth=json.dumps(teacher),tag='social_b',domain='social_b'))
        jsonl(out/(split+'.jsonl'),records);split_sizes[split]=len(records)
    dump(out/'manifest.json',dict(model=model,prompt_version=PROMPT_VERSION,reward=CONTRACT,
         training_unit='single_query',curriculum_version=CURRICULUM_VERSION if all(t.get('curriculum') for t in tasks) else None,
         files_sha256={s+'.jsonl':digest(out/(s+'.jsonl')) for s in ('train','validation','test')},
         splits=split_sizes,max_prompt_tokens=longest,data_hash=digest(data/'tasks.jsonl'),
         tokenizer_template_hash=__import__('hashlib').sha256(str(tokenizer.chat_template).encode()).hexdigest(),
         training='ROLL GRPO, actual generated token IDs, native Hermes parser, no retry during optimizer rollouts.'))
    print(json.dumps(dict(splits=split_sizes,max_prompt_tokens=longest)))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data-dir',required=True);p.add_argument('--output-dir',required=True);p.add_argument('--model',required=True)
    args=p.parse_args();export(args.data_dir,args.output_dir,args.model)
if __name__=='__main__':main()
