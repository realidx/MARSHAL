"""Score downloaded baseline replies; no test-set evaluation or label rewriting."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from training.b_sft.social_bp_grpo import read,sha
from training.b_sft.social_bp_training import reward,summarize


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',required=True);p.add_argument('--data',default='examples/social_bp/data/tasks.jsonl')
    a=p.parse_args();run=Path(a.run);bundle=run/'bundle';manifest=json.loads((bundle/'manifest.json').read_text())
    assert manifest['version']=='bp-pilot-baseline-v1'
    assert sha(a.data)==manifest['source_tasks_sha256'],'Teacher dataset changed since export'
    for name,digest in manifest['files'].items():assert sha(bundle/name)==digest
    tasks={t['id']:t for t in read(a.data)};out=run/'local_scoring';out.mkdir(exist_ok=False)
    reports={}
    for plan in manifest['stages']:
        folder=run/plan['name']
        if not (folder/'samples.jsonl').exists():continue
        config=json.loads((folder/'run_config.json').read_text())
        assert config['requests_sha256']==sha(bundle/plan['requests'])
        assert config['script_sha256']==sha(bundle/'remote_bp_probe.py')
        assert config['group_size']==plan['group_size'] and not config['preflight']
        permitted={r['task_id'] for r in read(bundle/plan['requests'])};seen=set();records=[];scored_rows=[];infra=0;per_question=Counter();success=Counter()
        for sample in read(folder/'samples.jsonl'):
            tid=sample['task_id'];idx=sample['sample_index']
            assert tid in permitted and (tid,idx) not in seen and 0<=idx<plan['group_size'];seen.add((tid,idx))
            task=tasks[tid];assert task['split']==plan['name']
            s=reward(task,sample);scored_rows.append(dict(sample,score=s))
            if s['reward'] is None:infra+=1;continue
            records.append(dict(task=task,score=s));per_question[tid]+=1;success[tid]+=bool(s['correct'])
        full=[tid for tid,n in per_question.items() if n==plan['group_size']]
        reports[plan['name']]=dict(received=len(scored_rows),planned=plan['formal_requests'],infrastructure_failures=infra,
            complete_groups=len(full),success_count_histogram=dict(Counter(success[tid] for tid in full)),
            measurements=summarize(records),partial=len(scored_rows)!=plan['formal_requests'],
            per_question=[dict(task_id=tid,samples=n,correct=success[tid],complete=n==plan['group_size']) for tid,n in per_question.items()])
        (out/(plan['name']+'_scored.jsonl')).write_text(''.join(json.dumps(s)+'\n' for s in scored_rows))
    (out/'summary.json').write_text(json.dumps(reports,indent=2)+'\n');print(json.dumps({k:{key:v[key] for key in ('received','planned','complete_groups','success_count_histogram','infrastructure_failures','partial')} for k,v in reports.items()},indent=2))


if __name__=='__main__':main()
