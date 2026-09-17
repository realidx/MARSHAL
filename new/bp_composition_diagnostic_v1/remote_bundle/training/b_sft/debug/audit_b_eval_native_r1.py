"""Read-only audit of downloaded native B evaluation; writes audit.json only."""
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from training.b_sft.social_b_evaluation import request, score_attempt, summarize

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'new/local_data/social_runs/b_eval_native_r1'
DATA=ROOT/'new/local_data/social_runs/b_curriculum_eval_v1'
def read(name, base=OUT): return list(map(json.loads,(base/name).read_text().splitlines()))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    calls=read('calls.jsonl');checks=read('checkpoints.jsonl');jobs=json.loads((OUT/'jobs.json').read_text())
    tasks={t['id']:t for t in read('tasks.jsonl',DATA)}
    cfg=json.loads((OUT/'run_config.json').read_text())
    failures=[]
    def check(condition,label):
        if not condition: failures.append(label)
    detail_only_differences=0
    source_matches={}
    for remote,h in cfg['source_hashes'].items():
        local=ROOT/remote.split('/mas/',1)[-1] if '/mas/' in remote else Path(remote)
        source_matches[remote]=local.is_file() and sha(local)==h
    data_matches={name:sha(DATA/name)==h for name,h in cfg['data_hashes'].items()}
    check(all(source_matches.values()),'source hashes');check(all(data_matches.values()),'data hashes')
    indexed=defaultdict(list)
    for r in calls:
        indexed[r['mode'],r['job'],r['checkpoint']].append(r)
        rescored=score_attempt(tasks[r['checkpoint']],r)
        if rescored!=r['score'] and {k:v for k,v in rescored.items() if k!='detail'}=={k:v for k,v in r['score'].items() if k!='detail'}:
            detail_only_differences+=1
        check({k:v for k,v in rescored.items() if k!='detail'}=={k:v for k,v in r['score'].items() if k!='detail'},'rescore '+r['checkpoint'])
        check(r['request']['tool_choice']=='auto' and not r['request']['parallel_tool_calls'],'native request')
    cindex={(r['mode'],r['job'],r['checkpoint']):r for r in checks}
    check(len(cindex)==len(checks),'unique checkpoints')
    serial_turns=0;total_tokens=[];unverified=0
    for mode,jid,ids in jobs:
        prior=[]
        for tid in ids:
            key=(mode,jid,tid);rs=indexed[key]
            check(1<=len(rs)<=2,'attempt count '+str(key))
            remaining=1024
            for i,r in enumerate(rs):
                check(r['attempt']==i,'attempt numbering')
                check(r['requested_max_tokens']==remaining==r['request']['max_tokens'],'remaining budget')
                feedback=None
                if i:
                    prev=rs[i-1]['score']
                    feedback=('Your previous response failed the submission format: '+prev.get('detail',prev['status'])+
                        '. Briefly explain, then submit exactly one native SUBMIT_BELIEFS tool call answering every query. '+
                        'Writing a function call in ordinary text does not submit it.')
                check(request(tasks[tid],mode=mode,prior_turns=prior,remaining_tokens=remaining,retry_feedback=feedback)==r['request'],
                      'exact prompt/gold isolation '+str(key))
                if 'usage' in r:
                    remaining-=r['usage']['completion_tokens']
                    check(0<=remaining<=1024,'token limit')
                else: remaining=0;unverified+=1
                check(r['remaining_tokens']==remaining,'logged remainder')
            total_tokens.append(sum(r.get('usage',{}).get('completion_tokens',0) for r in rs))
            cr=cindex[key]
            check(cr['first']==rs[0]['score'] and cr['final']==rs[-1]['score'],'first/final bookkeeping')
            check(cr['generated_tokens']==total_tokens[-1],'checkpoint tokens')
            if mode=='sequential' and rs[-1]['score']['status']!='infrastructure_failure':
                serial_turns+=len(prior)
                prior.append(dict(task=tasks[tid],message=rs[-1]['raw_message']))
    summary=json.loads((OUT/'summary.json').read_text())
    for mode in ('independent','sequential'):
        for which in ('first','final'):
            recomputed=summarize([r[which] for r in checks if r['mode']==mode])
            check(all(summary['modes'][mode][which][k]==v for k,v in recomputed.items()),'summary '+mode+which)
    metrics={}
    for mode in ('independent','sequential'):
        selected=[r for r in checks if r['mode']==mode]
        first=[r['first'] for r in selected];final=[r['final'] for r in selected]
        judgments=[j for r in final for j in r['judgments']]
        transitions=read('transitions.jsonl')
        trs=[r for r in transitions if r['mode']==mode]
        pair_queries={}
        for cat in ('formation','maintain','update','uninformative'):
            ps=[r for r in trs if r['category']==cat];correct=valid=0
            for p in ps:
                jid=p['after'] if mode=='independent' else p['job']
                score=cindex[mode,jid,p['after']]['final']
                if score['status']=='ok':
                    valid+=1
                    j=next(j for j in score['judgments'] if (j['player'],j['goal'])==(p['query']['player'],p['query']['goal']))
                    correct+=int(j['set_exact'] and j['favored_exact'])
            pair_queries[cat]=dict(pairs=len(ps),valid=valid,exact=correct)
        metrics[mode]=dict(first_statuses=dict(Counter(r['status'] for r in first)),final_statuses=dict(Counter(r['status'] for r in final)),
            final_exact=sum(r['exact'] is True for r in final),final_queries=len(judgments),
            full_set=sum(len(j['prediction']['possible_preferences'])==3 for j in judgments),
            multi_set_specific_favored=sum(len(j['prediction']['possible_preferences'])>1 and j['prediction']['favored']!='undetermined' for j in judgments),
            prediction_counts=dict(Counter(','.join(j['prediction']['possible_preferences'])+' / '+j['prediction']['favored'] for j in judgments)),
            queried_pair_results=pair_queries,
            retries=dict(Counter(r['score']['status'] for r in calls if r['mode']==mode and r['attempt']==1)))
    report=dict(validation_error_rendering_only_differences=detail_only_differences,calls=len(calls),checkpoints=len(checks),failures=failures,source_hashes_match=source_matches,data_hashes_match=data_matches,
        recorded_tokens_max_per_path=max(total_tokens),unverified_usage_requests=unverified,sequential_prior_messages_verified=serial_turns,
        modes=metrics,
        infrastructure_errors=[dict(checkpoint=r['checkpoint'],job=r['job'],error=r['error']) for r in calls if r['score']['status']=='infrastructure_failure'])
    (OUT/'audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
