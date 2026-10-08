"""Frozen terminal test from HF exports, with completion-refill HTTP inference."""
import argparse
from collections import deque,defaultdict
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
import json,math,time,threading
from pathlib import Path
from urllib.request import Request,urlopen
import numpy as np
from training.strategic_slices.common import seed_for,file_hash
from training.strategic_slices.terminal_training import TrainingData,StepRollout,mock_generate
from training.strategic_slices.terminal_candidates import sample_member_world
from training.strategic_slices.terminal_training_evaluate import FullGameView,Validator
from training.strategic_slices.runtime import Rollout
from training.strategic_slices.evaluate import summarize,interval
from training.strategic_slices.freeze import atomic_json
ROOT=Path(__file__).resolve().parents[2]


def refill(jobs,generate,request,accept,workers):
    ready=deque(j for j in jobs if j.status=='running');active={};completed=0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        while ready or active:
            while ready and len(active)<workers:
                job=ready.popleft();req=request(job);active[pool.submit(generate,req)]=(job,req)
            done,_=wait(active,return_when=FIRST_COMPLETED)
            for future in done:
                job,req=active.pop(future);accept(job,future.result(),req)
                if job.status=='running':ready.append(job)
                else:
                    completed+=1
                    if completed%100==0:print('Completed episodes',completed,'/',len(jobs),flush=True)


class Generator:
    def __init__(self,args):
        from transformers import AutoTokenizer
        from vllm.tool_parsers.hermes_tool_parser import Hermes2ProToolParser
        self.tokenizer=AutoTokenizer.from_pretrained(args.model,local_files_only=True)
        self.parser=Hermes2ProToolParser(self.tokenizer);self.args=args;self.lock=threading.Lock()
    def __call__(self,req):
        from training.b_sft.social_b_grpo import parse_completion
        with self.lock:
            ids=self.tokenizer.apply_chat_template(req['messages'],tools=req['tools'],tokenize=True,add_generation_prompt=True,return_dict=True,truncation=False)['input_ids']
        limit=req.get('max_tokens',1024)
        if len(ids)+limit>16384:raise ValueError('Context overflow; refusing truncation')
        body=dict(model='terminal-eval',prompt=ids,max_tokens=limit,temperature=0.,top_p=1.,top_k=-1,repetition_penalty=1.,seed=req['seed'],logprobs=0,return_tokens_as_token_ids=True,stop_token_ids=[self.tokenizer.eos_token_id])
        started=time.monotonic()
        with urlopen(Request(self.args.url+'/completions',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'}),timeout=600) as handle:result=json.load(handle)
        with self.lock:
            with (self.args.output/'requests.jsonl').open('a') as log:
                log.write(json.dumps(dict(request=body,response=result))+'\n')
        choice=result['choices'][0];logs=choice['logprobs'];tokens=logs['tokens']
        if not all(t.startswith('token_id:') for t in tokens):raise ValueError('Missing exact token IDs')
        response=[int(t.split(':')[1]) for t in tokens];probs=logs['token_logprobs']
        if not response or len(response)!=len(probs) or not all(math.isfinite(p) for p in probs):raise ValueError('Invalid token/logprob evidence')
        if result['usage']['prompt_tokens']!=len(ids) or len(response)!=result['usage']['completion_tokens']:raise ValueError('Token counts differ')
        text=self.tokenizer.decode(response,skip_special_tokens=False)
        with self.lock:
            completion=parse_completion(self.parser,text,req['tools'],truncated=choice['finish_reason']=='length')
        return dict(prompt_ids=ids,response_ids=response,behavior_log_probs=probs,text=text,finish_reason=choice['finish_reason'],completion=completion,request=req,usage=result['usage'],elapsed_seconds=time.monotonic()-started)


def evaluate(data,generate,cfg,repeats,limit=None):
    selected=sorted(data.test,key=lambda r:r['id'])
    if limit:selected=selected[:limit]
    selected=sorted(selected,key=lambda r:(r['parent_id'],r['id']))
    jobs=[]
    for row in selected:
        tree,cache=data.reference(row)
        for replica in range(repeats):
            seed=seed_for(cfg['seed'],'terminal-test',row['id'],replica)
            jobs.append(StepRollout(tree,row,replica,seed,sample_member_world(row,np.random.default_rng(seed)),cache=cache))
    refill(jobs,generate,lambda j:j.request(cfg),lambda j,o,r:j.accept(o,r),cfg['workers'])
    records=[];calls=[]
    for job in jobs:
        record=job.record();record.pop('calls');record.update(step_rewards=job.step_rewards);records.append(record)
        calls.extend(dict(c,oracle_step=d,slice_id=job.row['id'],replica=job.replica) for c,d in zip(job.calls,job.step_details))
    rewards=[v for r in records for v in r['step_rewards']];completed=[r['utility'] for r in records if r['status']=='terminal']
    full_data=FullGameView(data,{r['parent_id'] for r in selected},'test');metrics={};games=[];full_calls=[]
    for mode in ['team','focal_reference']:
        cohort=[]
        for parent in full_data.parents['test']:
            for item in ([None] if mode=='team' else range(parent['players'])):
                for replica in range(repeats):
                    seed=seed_for(cfg['seed'],'evaluation',parent['id'],mode,item,replica)
                    wi=int(np.random.default_rng(seed).choice(len(parent['world_weights']),p=parent['world_weights']))
                    cohort.append(Rollout(full_data,parent,seed,wi,focal=item if mode=='focal_reference' else None))
        refill(cohort,generate,lambda j:dict(j.request(0.),max_tokens=1024,top_p=1.,top_k=-1,repetition_penalty=1.),lambda j,o,r:j.accept(o),cfg['workers'])
        metrics[mode]=summarize(cohort)
        for i,j in enumerate(cohort):
            eid=f'{mode}:{i}';games.append(dict(j.summary(),mode=mode,evaluation_id=eid,seed=j.seed,world=[list(r) for r in j.world]))
            full_calls.extend(dict(c,mode=mode,parent_id=j.parent['id'],evaluation_id=eid) for c in j.calls)
    return dict(protocol=dict(split='test',repeats=repeats,temperature=0.,max_tokens=1024,context=16384,limit=limit,execution='completion-refill-global-v1',workers=cfg['workers']),
        generated_response_tokens=sum(len(c['response_ids']) for c in calls+full_calls),
        slices=dict(episodes=len(records),completion_rate=len(completed)/len(records),per_decision_accuracy=sum(rewards)/len(rewards),terminal_utility_completed=interval(completed),full_window_success_rate=sum(r['status']=='terminal' and all(r['step_rewards']) for r in records)/len(records)),
        slice_games=records,slice_calls=calls,full_games=dict(metrics=metrics,games=games,calls=full_calls))


def main():
    cli=argparse.ArgumentParser();cli.add_argument('--model',type=Path);cli.add_argument('--url');cli.add_argument('--output',type=Path,required=True);cli.add_argument('--workers',type=int,default=64);cli.add_argument('--repeats',type=int,default=8);cli.add_argument('--limit',type=int);cli.add_argument('--mock',action='store_true');a=cli.parse_args()
    data=TrainingData(ROOT/'new/local_data/strategic_slices_oracle_consistent_candidates_v4',ROOT/'new/local_data/strategic_slices_terminal_selected_v4')
    cfg=dict(seed=42,workers=a.workers,max_tokens=1024,context=16384,temperature=0.,top_p=1.,top_k=-1,repetition_penalty=1.)
    generate=(lambda req:mock_generate([req])[0]) if a.mock else Generator(a)
    a.output.mkdir(parents=True,exist_ok=False);report=evaluate(data,generate,cfg,a.repeats,a.limit)
    if a.mock:
        baseline=Validator(data,mock_generate,cfg,repeats=a.repeats,limit=a.limit,split='test').run()
        for key in ['slices','slice_games','slice_calls','generated_response_tokens']:assert report[key]==baseline[key],key
        for key in ['metrics','games','calls']:assert report['full_games'][key]==baseline['full_games'][key],key
        report['mock_exact_match']=True
    report.update(model=str(a.model),dataset_sha256=data.sha,used_for_checkpoint_selection=False,historical_test_exposure='Previously used in base-model D analysis; not blind.')
    atomic_json(a.output/'report.json',report);atomic_json(a.output/'COMPLETE.json',dict(report_sha256=file_hash(a.output/'report.json'),mock=a.mock));print(json.dumps(report['slices']),flush=True)
if __name__=='__main__':main()
