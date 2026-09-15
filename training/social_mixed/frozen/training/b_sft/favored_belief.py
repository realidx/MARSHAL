"""Marginal set/favored supervision over explicit joint preference hypotheses.

Weights stay teacher-only. The native prior is uniform over unique Cartesian
profiles; observed partner actions filter worlds, learner actions do not.
"""
from collections import Counter, deque, defaultdict
from copy import deepcopy
from itertools import product
import argparse
import math
import json
from pathlib import Path
import time

from training.social_mixed.frozen.training.b_sft.evidence_switch import constructed, decision_key, disjoint
from training.social_mixed.frozen.training.b_sft.structure_audit import Fixture, digest, TOL, structure_id
from training.social_mixed.frozen.benac_p.endgame import SearchLimit
from training.social_mixed.frozen.benac_p.endgame_partner import InformationStateRequired

LABELS={1:'want',0:'neutral',-1:'avoid'}


def marginal(worlds,player,goal,robustness_ratio=1.25):
    if not math.isfinite(robustness_ratio) or robustness_ratio<1:raise ValueError('robustness_ratio must be >= 1')
    if not worlds or len(worlds)!=len(set(worlds)):raise ValueError('Expected nonempty unique worlds')
    counts=Counter(LABELS[w[player][goal]] for w in worlds)
    support=[label for label in LABELS.values() if counts[label]]
    ranked=sorted(counts,key=lambda x:-counts[x])
    # A unique winner survives any multiplicative reweighting of individual
    # remaining worlds in [1, ratio]. This does not vary the partner policy.
    favored=ranked[0] if len(ranked)==1 or counts[ranked[0]]>robustness_ratio*counts[ranked[1]] else 'undetermined'
    return dict(answer=dict(possible_preferences=support,favored=favored),
                teacher_counts={k:counts[k] for k in support},robustness_ratio=robustness_ratio,
                assumption='Uniform unique joint worlds, deterministic declared partner; robustness only to bounded remaining-world reweighting.')


def score_belief(answer,gold):
    """Semantic reward, not token CE; missing teacher components are masked."""
    if not isinstance(answer,dict) or set(answer)!={'possible_preferences','favored'}:
        return dict(score=-1.,format_valid=False)
    s=answer['possible_preferences'];f=answer['favored']
    if (not isinstance(s,list) or not s or any(not isinstance(x,str) or x not in LABELS.values() for x in s)
        or len(set(s))!=len(s) or not isinstance(f,str) or f not in s+['undetermined']
        or len(s)==1 and f!=s[0]):return dict(score=-1.,format_valid=False)
    if gold is None:return dict(score=None,format_valid=True,teacher_mask=False)
    target=gold.get('possible_preferences');fav=gold.get('favored')
    parts=[]
    if target is not None:parts.append(-.5*len(set(s)^set(target))/3)
    if fav is not None:parts.append(-.5*int(f!=fav))
    return dict(score=sum(parts) if parts else None,format_valid=True,teacher_mask=bool(parts),
                set_mask=target is not None,favored_mask=fav is not None)


def joint_candidate(seed):
    raw=constructed(seed);raw['id']=f'favored-joint-{seed}'
    target=raw['query']['player'];g=raw['query']['goals'][0]
    extra=next(x for x in [0,2,3] if x!=g)
    row=raw['type_catalogues'][str(target)][0][:]
    # Keep at least one fixed want so every joint profile remains admissible.
    fixed=next(x for x in range(4) if x not in (g,extra));row[fixed]=1
    raw['type_catalogues'][str(target)]=[[(dict(zip([g,extra],vs))).get(i,v) for i,v in enumerate(row)] for vs in product((1,0,-1),repeat=2)]
    raw['query']['goals']=[g,extra]
    raw['assessed_goal']=g
    raw['source']['generator']='favored_belief.joint_candidate'
    return raw


def load_fixture(raw,max_nodes):
    if 'initially_possible_preferences' in raw:
        raise ValueError('Do not inject a posterior; infer it from visible history')
    if any(not g.get('binary',True) for g in raw['game']['goals']):
        raise ValueError('Linear goals unsupported by native Fixture renderer')
    if raw['assessed_goal'] not in raw['query']['goals']:
        raise ValueError('Assessed goal must be a declared hidden dimension')
    return Fixture(raw,max_nodes)


def export_pair(witness,out,max_nodes=3000):
    """Development B targets; P values remain a teacher-only diagnostic."""
    raw=witness['fixture'];f=load_fixture(raw,max_nodes)
    records=[];gold=[]
    tool=dict(type='function',function=dict(name='submit_belief',description='Submit the marginal partner judgment.',
        parameters=dict(type='object',additionalProperties=False,required=['possible_preferences','favored'],
        properties=dict(possible_preferences=dict(type='array',minItems=1,maxItems=3,uniqueItems=True,
                         items=dict(type='string',enum=list(LABELS.values()))),
                        favored=dict(type='string',enum=list(LABELS.values())+['undetermined'])))))
    for side in ['left','right']:
        row=witness[side];sample_id=raw['id']+'/'+side
        payload=dict(game=raw['game'],ego=raw['ego'],own_preferences=raw['own_preferences'],
                     public_type_catalogues=raw['type_catalogues'],partner_model=f.partner.specification(),
                     history=row['history'],query=dict(player=raw['query']['player'],goal=raw['assessed_goal']),
                     favored_rule=dict(prior='Uniform over unique joint profiles; condition on public partner actions.',
                         robustness_ratio=witness['robustness_ratio'],
                         rule='Choose the unique leading marginal only if it stays ahead under individual remaining-world weight multipliers between 1 and robustness_ratio; otherwise undetermined. Singleton sets favor their sole element.'))
        record=dict(id=sample_id,source_id=structure_id(raw),split='development',task='B',
                    teacher_version='joint-marginal-v1',training_ready=False,messages=[
            dict(role='system',content='Use only visible information. Submit the possible marginal preferences and one favored preference or undetermined. Do not output probabilities or counts.'),
            dict(role='user',content=json.dumps(payload)),
            dict(role='assistant',content='',tool_calls=[dict(id='call_belief',type='function',function=dict(
                 name='submit_belief',arguments=json.dumps(row['belief']['answer'])))])],tools=[tool])
        records.append(record)
        gold.append(dict(id=sample_id,**row['belief'],planning_q=row['q'],optimal_actions=row['optimal_actions']))
    for name,rows in [('development.jsonl',records),('development_prompts.jsonl',[dict(r,messages=r['messages'][:-1]) for r in records]),('development_gold.jsonl',gold)]:
        (out/name).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
    (out/'pair.json').write_text(json.dumps(dict(left_B=records[0]['id'],right_B=records[1]['id'],source_id=structure_id(raw),
        relation='contrast_between_histories_not_temporal_update',same_set=True,favored_differs=True,
        planning_switch=witness['planning_switch'],training_ready=False),indent=2)+'\n')


def inspect_node(f,node,history,goal,ratio):
    q=f.search.q_values(node);best=max(v for _,v in q)
    return dict(history=history,physical_key=decision_key(node),
                belief=marginal(node.worlds,f.target_player,goal,ratio),
                actions=[a.to_dict() for a,_ in q],q=[v for _,v in q],
                optimal_actions=[i for i,(_,v) in enumerate(q) if best-v<=TOL])


def verify(witness,max_nodes=3000):
    rows=[]
    for side in ['left','right']:
        expected=witness[side];raw=deepcopy(witness['fixture']);raw['history']=expected['history']
        f=load_fixture(raw,max_nodes)
        actual=inspect_node(f,f.root,raw['history'],raw['assessed_goal'],witness['robustness_ratio'])
        if actual!=expected:raise ValueError('Independent favored replay mismatch')
        rows.append(actual)
    a,b=rows
    if (a['physical_key']!=b['physical_key'] or a['actions']!=b['actions']
        or a['belief']['answer']['possible_preferences']!=b['belief']['answer']['possible_preferences']
        or a['belief']['answer']['favored']==b['belief']['answer']['favored']):
        raise ValueError('Not a matched-state same-set favored contrast')
    if witness['planning_switch']!=disjoint(a,b):raise ValueError('Planning switch mismatch')
    return True


def mine(raw,max_nodes=3000,max_decisions=128,depth=4,ratio=1.25):
    start=time.monotonic();result=dict(id=raw['id'],status='complete',visited=0,witness=None)
    try:
        f=load_fixture(raw,max_nodes);queue=deque([(f.root,raw.get('history',[]),0)]);seen=set();groups=defaultdict(list)
        while queue:
            if result['visited']>=max_decisions:result['status']='decision_budget';break
            node,history,d=queue.popleft();key=digest(history)
            if key in seen or node.state.is_terminal:continue
            seen.add(key);result['visited']+=1
            row=inspect_node(f,node,history,raw['assessed_goal'],ratio)
            for old in groups[row['physical_key']]:
                a,b=old['belief']['answer'],row['belief']['answer']
                if a['possible_preferences']==b['possible_preferences'] and a['favored']!=b['favored'] and old['actions']==row['actions']:
                    w=dict(fixture=raw,left=old,right=row,robustness_ratio=ratio,planning_switch=disjoint(old,row),
                           limitation='Multiple hidden goals: a planning difference is not attributable exclusively to this marginal favored field.')
                    if result['witness'] is None or w['planning_switch']:result['witness']=w
                    if w['planning_switch']:break
            if result['witness'] and result['witness']['planning_switch']:result['status']='found_planning_switch';break
            groups[row['physical_key']].append(row)
            if d<depth:
                for action in f.search.actions(node):
                    for b in f.window_step(node,action):
                        if not b.node.state.is_terminal:
                            queue.append((b.node,history+[action.to_dict()]+[e['action'] for e in b.evidence],d+1))
    except (SearchLimit,InformationStateRequired,ValueError) as exc:
        result.update(status='unavailable',reason=f'{type(exc).__name__}: {exc}')
    result['seconds']=round(time.monotonic()-start,3)
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--seed',type=int,default=95000);p.add_argument('--seeds',type=int,default=24)
    p.add_argument('--max-nodes',type=int,default=3000);p.add_argument('--max-decisions',type=int,default=128)
    p.add_argument('--depth',type=int,default=4);p.add_argument('--robustness-ratio',type=float,default=1.25)
    args=p.parse_args(argv)
    if args.output_dir.exists():p.error('Use a new output directory')
    if min(args.seeds,args.max_nodes,args.max_decisions)<1 or args.depth<0 or (not math.isfinite(args.robustness_ratio) or args.robustness_ratio<1):p.error('Invalid budget or ratio')
    args.output_dir.mkdir(parents=True);results=[];best=None
    with (args.output_dir/'attempts.jsonl').open('w') as out:
        for seed in range(args.seed,args.seed+args.seeds):
            r=mine(joint_candidate(seed),args.max_nodes,args.max_decisions,args.depth,args.robustness_ratio)
            results.append(r);out.write(json.dumps(r)+'\n');out.flush()
            print(json.dumps({k:r[k] for k in ['id','status','visited','seconds']}|dict(favored_pair=bool(r['witness']))),flush=True)
            if r['witness'] and (best is None or r['witness']['planning_switch']):
                verify(r['witness'],args.max_nodes);best=r['witness']
                (args.output_dir/'witness.json').write_text(json.dumps(best,indent=2)+'\n')
            if best and best['planning_switch']:break
    if best:export_pair(best,args.output_dir,args.max_nodes)
    (args.output_dir/'summary.json').write_text(json.dumps(dict(version='joint-marginal-v1',arguments={k:str(v) if isinstance(v,Path) else v for k,v in vars(args).items()},
        statuses={s:sum(r['status']==s for r in results) for s in sorted({r['status'] for r in results})},
        attempts=len(results),found=bool(best),
        planning_switch=bool(best and best['planning_switch']),seconds=sum(r['seconds'] for r in results),
        training_ready=False,scope='Development joint-prior reference; no probability output targets, no isolated causal claim for marginal favored.'),indent=2)+'\n')


if __name__=='__main__':main()
