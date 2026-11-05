"""Recompute reward probe and attribute group variation to queried categories."""
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from training.b_sft.social_b_rl import read, reward, analyze, source_hashes
from training.b_sft.social_b_evaluation import request, score_attempt
ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'new/local_data/social_runs/b_rl_reward_probe_r1'
DATA=ROOT/'new/local_data/social_runs/b_curriculum_eval_v1'
def main():
    calls=read(OUT/'calls.jsonl');cfg=json.loads((OUT/'run_config.json').read_text())
    tasks={t['id']:t for t in read(DATA/'tasks.jsonl')};selection=cfg['selection'];pairs=read(DATA/'pairs.jsonl')
    failures=[]
    def check(x,label):
        if not x:failures.append(label)
    check(cfg['source_hashes']==source_hashes(),'source hashes')
    manifest=json.loads((ROOT/'new/local_data/social_runs/b_rl_prepare_v1/manifest.json').read_text())
    check(manifest['task_hash']==hashlib.sha256((DATA/'tasks.jsonl').read_bytes()).hexdigest(),'tasks hash')
    check(selection==json.loads((ROOT/'new/local_data/social_runs/b_rl_prepare_v1/probe_selection.json').read_text()),'selection')
    paths=defaultdict(list)
    for r in calls:
        t=tasks[r['checkpoint']];paths[r['checkpoint'],r['sample']].append(r)
        check(reward(t,r)==r['rl_reward'],'reward')
        score=score_attempt(t,r)
        check({k:v for k,v in score.items() if k!='detail'}=={k:v for k,v in r['score'].items() if k!='detail'},'score')
        expected_seed=int.from_bytes(hashlib.sha256(f"{cfg['arguments']['seed']}:{r['checkpoint']}:{r['sample']}".encode()).digest()[:4],'big')%(2**31)
        check(r['seed']==expected_seed,'seed')
    check(len(paths)==96,'96 paths')
    for chosen in selection:
        check(tasks[chosen['id']]['split']=='train','train only')
        check({s for tid,s in paths if tid==chosen['id']}==set(range(8)),'eight distinct sample indices')
    maximum=0
    for (tid,sample),rs in paths.items():
        rs.sort(key=lambda r:r['attempt']);check(1<=len(rs)<=2,'retry limit');remaining=1024
        for i,r in enumerate(rs):
            check(r['attempt']==i,'attempt order')
            check(r['request']['max_tokens']==r['requested_max_tokens']==remaining,'request budget')
            feedback=None
            if i:
                previous=rs[i-1]['score']
                feedback=('Your previous response failed the submission format: '+previous.get('detail',previous['status'])+
                    '. Briefly explain, then submit exactly one native SUBMIT_BELIEFS tool call answering every query. '+
                    'Writing a function call in ordinary text does not submit it.')
            check(request(tasks[tid],remaining_tokens=remaining,retry_feedback=feedback)==r['request'],'exact prompt/no gold')
            remaining-=r['usage']['completion_tokens']
            check(remaining>=0 and remaining==r['remaining_tokens'],'actual budget')
        maximum=max(maximum,1024-remaining)
    ordered=sorted(calls,key=lambda r:(r['checkpoint'],r['sample'],r['attempt']))
    check(analyze(ordered,tasks,selection,8)==json.loads((OUT/'summary.json').read_text()),'summary recomputation')
    per_query=[]
    for chosen in selection:
        for p in pairs:
            if p['after']!=chosen['id'] or p['category']!=chosen['category']:continue
            key=(p['query']['player'],p['query']['goal']);values=[]
            for sample in range(8):
                s=paths[chosen['id'],sample][0]['score']
                if s['status']!='ok':values.append(None);continue
                j=next(j for j in s['judgments'] if (j['player'],j['goal'])==key)
                values.append(int(j['set_exact'] and j['favored_exact']))
            per_query.append(dict(**chosen,query=p['query'],first_query_correct=values,correct=sum(v==1 for v in values),valid=sum(v is not None for v in values)))
    category={}
    for cat in ('formation','maintain','update','uninformative'):
        rows=[r for r in per_query if r['category']==cat]
        category[cat]=dict(query_groups=len(rows),scheduled=8*len(rows),valid=sum(r['valid'] for r in rows),correct=sum(r['correct'] for r in rows),
                           groups_with_query_variation=sum(0 in r['first_query_correct'] and 1 in r['first_query_correct'] for r in rows))
    report=dict(failures=failures,requests=len(calls),paths=len(paths),max_generated_tokens_per_path=maximum,
        first_statuses=dict(Counter(rs[0]['score']['status'] for rs in paths.values())),
        final_statuses=dict(Counter(rs[-1]['score']['status'] for rs in paths.values())),
        first_reward_counts=dict(Counter(str(rs[0]['rl_reward']['reward']) for rs in paths.values())),
        category_query_results=category,per_query=per_query,
        qualification='Category correctness is for the query defining that category; another query can produce partial reward. Eight samples cannot establish that success probability is zero.')
    (OUT/'audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='per_query'},indent=2))
if __name__=='__main__':main()
