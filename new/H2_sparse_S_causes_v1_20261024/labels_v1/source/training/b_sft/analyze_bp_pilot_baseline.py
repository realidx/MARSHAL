"""Summarize a downloaded frozen baseline without editing data/reward/curriculum."""
import argparse
from collections import Counter,defaultdict
import json
from pathlib import Path
from training.b_sft.social_bp_grpo import read
from training.b_sft.social_bp_training import select_batch


def analyze(run,data):
    run=Path(run);tasks={t['id']:t for t in read(data)};rows=[];all_samples=[];summaries={}
    for split,n in (('train',8),('validation',4)):
        samples=read(run/'local_scoring'/f'{split}_scored.jsonl');all_samples.extend(samples);groups=defaultdict(list)
        for s in samples:groups[s['task_id']].append(s)
        for tid,ss in groups.items():
            t=tasks[tid];assert len(ss)==n;success=sum(bool(s['score']['correct']) for s in ss)
            rows.append(dict(id=tid,split=split,task=t['task'],pool=t['pool'],stage=t['stage'],direct=t['direct_answer'],
                correct=success,n=n,truncated=sum(s['score']['status']=='truncated' for s in ss),
                group_status='zero' if success==0 else 'all' if success==n else 'mixed'))
        split_summary={}
        for kind in ('B','P'):
            rr=[r for r in rows if r['split']==split and r['task']==kind]
            ss=[s for s in samples if tasks[s['task_id']]['task']==kind]
            split_summary[kind]=dict(questions=len(rr),samples=len(ss),correct=sum(r['correct'] for r in rr),
                statuses=dict(Counter(s['score']['status'] for s in ss)),groups=dict(Counter(r['group_status'] for r in rr)))
        b=[s for s in samples if tasks[s['task_id']]['task']=='B' and not tasks[s['task_id']]['direct_answer']]
        legal=[s for s in b if s['score']['status']=='ok'];full=[s for s in legal if s['score']['predicted_full_set']]
        split_summary['behavior_b']=dict(samples=len(b),correct=sum(s['score']['correct'] for s in b),valid_submissions=len(legal),
            fullset_submissions=len(full),wrong_fullset_set=sum(not s['score']['set_exact'] for s in full),
            fullset_wrong_favored_only=sum(s['score']['set_exact'] and not s['score']['favored_exact'] for s in full))
        pools={}
        for pool in ('formation','maintain','update','complete','uncertain','result_use','information'):
            for stage in range(3):
                rr=[r for r in rows if r['split']==split and r['pool']==pool and r['stage']==stage]
                pools[f'{pool}/{stage}']=dict(questions=len(rr),samples=sum(r['n'] for r in rr),correct=sum(r['correct'] for r in rr),
                    truncated=sum(r['truncated'] for r in rr),groups=dict(Counter(r['group_status'] for r in rr)))
        split_summary['pools']=pools
        contrast=defaultdict(list)
        for t in tasks.values():
            if t['split']==split:contrast[t['task'],t['stage'],t['contrast_group']].append(t)
        split_summary['different_answer_contrast_groups']={f'{kind}/{stage}':sum(k==kind and s==stage and len({t['answer_signature'] for t in ts})>1 for (k,s,g),ts in contrast.items()) for kind in ('B','P') for stage in range(3)}
        summaries[split]=split_summary
    by_id={r['id']:r for r in rows};train=[t for t in tasks.values() if t['split']=='train'];simulation={}
    for scenario,allowed in (('held_easy',0),('fully_progressed',2)):
        counts=Counter()
        for step in range(100):
            selected=select_batch(train,step,100,16,20260914,dict(allowed={'B':allowed,'P':allowed}))
            counts.update((t['task'],by_id[t['id']]['group_status']) for t in selected)
        simulation[scenario]={f'{kind}/{status}':counts[kind,status] for kind in ('B','P') for status in ('zero','mixed','all')}
    return dict(splits=summaries,questions=rows,frozen_group_resampling=simulation,
        simulation_scope='Reweight these observed groups under the planned sampler. This is not a prediction of new rollout success or gradient magnitude.')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',required=True);p.add_argument('--data',default='examples/social_bp/data/tasks.jsonl');p.add_argument('--out',required=True)
    a=p.parse_args();Path(a.out).write_text(json.dumps(analyze(a.run,a.data),indent=2)+'\n')
