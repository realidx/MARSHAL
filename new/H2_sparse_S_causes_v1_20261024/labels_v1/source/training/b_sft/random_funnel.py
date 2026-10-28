"""Budgeted random structures and independent ego paths with stage accounting."""
import argparse
from collections import Counter
from copy import deepcopy
import json
import math
from pathlib import Path
import random
import time

from training.b_sft.structure_audit import Fixture,structure_id,digest,TOL
from training.b_sft.social_rollout import queries_for, build
from types import SimpleNamespace
from training.b_sft.favored_belief import marginal
from benac_p.endgame_mine import candidates
from benac_p.endgame import SearchLimit
from benac_p.endgame_partner import InformationStateRequired


def screen(raw,max_nodes=1000,max_arms=8):
    result=dict(id=raw['id'],source_id=structure_id(raw),stage='replay',status='unavailable',categories=[])
    start=time.monotonic()
    try:
        search,node,types,partner=build(raw,max_nodes)
        f=SimpleNamespace(search=search,root=node,types=types,ego=search.ego,window_step=search.step)
        queries=queries_for(f.types,f.ego)
        before=[dict(**q,**marginal(f.root.worlds,q['player'],q['goal'])['answer']) for q in queries]
        actions=f.search.actions(f.root)
        result.update(joint_worlds=len(f.root.worlds),legal_actions=len(actions),B=before)
        if len(actions)<2 or len(f.root.worlds)<2:
            result.update(stage='cheap_screen',status='ordinary_control',reason='No remaining uncertainty or no action choice')
            return result
        result['stage']='evidence_screen'
        sampled=list(actions);random.Random(int(digest(raw['history'])[:8],16)).shuffle(sampled)
        sampled=sampled[:max_arms];arms=[]
        for a in sampled:
            branches=f.window_step(f.root,a)
            evidence=[]
            for b in branches:
                after=[dict(**q,**marginal(b.node.worlds,q['player'],q['goal'])['answer']) for q in queries]
                evidence.append(dict(weight=b.weight,terminal=b.node.state.is_terminal,after_B=after,evidence=b.evidence))
            arms.append(dict(action=a.to_dict(),branches=evidence))
        result.update(sampled_arms=len(arms),all_arms_examined=len(arms)==len(actions),arms=arms)
        live=[b for a in arms for b in a['branches'] if not b['terminal']]
        if any(b['after_B']==before for b in live):result['categories'].append('maintain_with_later_decision')
        if any(b['after_B']!=before for b in live):result['categories'].append('update_with_later_decision')
        if any(len(x['possible_preferences'])>1 and x['favored']!='undetermined' for b in live for x in b['after_B']):
            result['categories'].append('nontrivial_favored')
        informative=[a for a in arms if any(not b['terminal'] and b['after_B']!=before for b in a['branches'])]
        if not informative:
            result.update(status='ordinary_control',reason='No informative live branch among sampled arms')
            return result
        result['stage']='terminal_value_verification'
        q=f.search.q_values(f.root);best=max(v for _,v in q)
        result['Q']=[dict(action=a.to_dict(),value=v) for a,v in q]
        spread=best-min(v for _,v in q)
        result.update(root_q_range=spread,p_auxiliary_mask=spread>TOL,
                      next_evidence_use_checked=False)
        for a in informative:
            v=next(v for act,v in q if act.to_dict()==a['action'])
            a['root_regret']=best-v
        if any(a['root_regret']>TOL for a in informative):result['categories'].append('costly_information_control')
        if spread<=TOL:result['categories'].append('P_action_invariant_control')
        elif any(a['root_regret']<=TOL for a in informative):result['categories'].append('informative_action_tied_or_best')
        result.update(status='verified',positive_net_information_value_proven=False,
                      tie_sensitivity_checked=False,core_social_reasoning_certified=False,
                      scope='Fixed-policy candidate/control only. Requires tie sensitivity and evidence-use audit before core selection; no positive net information-value certificate.')
    except (SearchLimit,InformationStateRequired,ValueError) as exc:
        result['reason']=f'{type(exc).__name__}: {exc}'
    finally:result['seconds']=round(time.monotonic()-start,3)
    return result


def run(args):
    out=args.output_dir
    if out.exists():raise ValueError('Use a new output directory')
    out.mkdir(parents=True)
    events=[];results=[];kept=[];seen=set();sources=set();configs=set();requests=0
    started=time.monotonic();stop=False
    with (out/'events.jsonl').open('w') as ef,(out/'decisions.jsonl').open('w') as df,(out/'retained.jsonl').open('w') as kf:
        def event(e,context):
            e=dict(context,**e)
            if e['event']=='game_generated':
                e['source_id']=structure_id(dict(game=e.pop('game')));sources.add(e['source_id'])
            if e['event']=='configuration_started':configs.add((e['seed'],tuple(e['goals'])))
            events.append(e);ef.write(json.dumps(e)+'\n');ef.flush()
        for n in args.players:
            for seed in range(args.seed,args.seed+args.seeds):
                actual_seed=seed+(n-3)*1000000
                for unknown in args.hidden_goals:
                    for trajectory in range(args.trajectories):
                        if time.monotonic()-started>=args.seconds:stop=True;break
                        requests+=1;context=dict(seed=actual_seed,players=n,hidden_goals=unknown,path=trajectory)
                        yielded=0
                        try:
                            iterator=candidates(actual_seed,args.max_nodes,args.actions,args.goals,2,unknown,
                                None,args.remaining_turns,args.query_sets,n_players=n,
                                trajectory_seed=actual_seed+trajectory*100000007,
                                on_event=lambda e:event(e,context))
                            for raw in iterator:
                                yielded+=1
                                if time.monotonic()-started>=args.seconds:
                                    event(dict(event='path_sampling_truncated',seed=actual_seed,reason='wall budget at candidate boundary'),context)
                                    stop=True;break
                                raw=deepcopy(raw);raw['id']+=f'-path{trajectory}'
                                key=digest(dict(source=structure_id(raw),types=raw['type_catalogues'],ego=raw['ego'],history=raw['history']))
                                if key in seen:
                                    event(dict(event='duplicate_decision',seed=actual_seed),context);continue
                                seen.add(key);r=screen(raw,args.max_nodes,args.max_arms);r.update(context)
                                results.append(r);df.write(json.dumps(r)+'\n');df.flush()
                                if r['status'] in ('verified','ordinary_control'):
                                    item=dict(fixture=raw,screen=r,split='development')
                                    kept.append(item);kf.write(json.dumps(item)+'\n');kf.flush()
                            iterator.close()
                        except (RuntimeError,ValueError) as exc:
                            event(dict(event='generation_exception',seed=actual_seed,reason=f'{type(exc).__name__}: {exc}'),context)
                        print(json.dumps(dict(players=n,seed=actual_seed,hidden=unknown,path=trajectory,yielded=yielded,unique_decisions=len(results))),flush=True)
                        if stop:break
                    if stop:break
                if stop:break
            if stop:break
    ec=Counter(e['event'] for e in events);statuses=Counter(r['status'] for r in results)
    summary=dict(arguments={k:str(v) if isinstance(v,Path) else v for k,v in vars(args).items()},
        elapsed_seconds=round(time.monotonic()-started,2),wall_budget_reached=stop,
        structures=len(sources),configurations=len(configs),path_requests=requests,
        trajectories_started=ec['configuration_started'],trajectories_finished=ec['trajectory_finished'],
        trajectory_failures=ec['trajectory_failed'],
        total_ego_decisions_in_finished_paths=sum(e['ego_decisions'] for e in events if e['event']=='trajectory_finished'),
        control_reasons=dict(Counter(r['reason'] for r in results if r['status']=='ordinary_control')),
        by_stratum={f'n{n}_hidden{h}':dict(decisions=sum(r['players']==n and r['hidden_goals']==h for r in results),
            verified=sum(r['players']==n and r['hidden_goals']==h and r['status']=='verified' for r in results)) for n in args.players for h in args.hidden_goals},events=dict(ec),unique_decisions=len(results),statuses=dict(statuses),
        failed_stages=dict(Counter(r['stage'] for r in results if r['status']=='unavailable')),
        coverage=dict(Counter(c for r in results if r['status']!='unavailable' for c in r['categories'])),
        verified_structures=len({r['source_id'] for r in results if r['status']=='verified'}),
        retained=len(kept),training_ready=False,
        limits=['Wall budget checked only between requests/candidates; not hard preemption.',
                'Random ego interventions, fixed RationalPartner; early path construction itself requires partner search.',
                'One generated realized preference matrix per game seed; hidden catalogues vary queried dimensions.',
                '1/2 hidden goals in one partner; no multi-partner uncertainty in this miner.',
                'Trajectories run from start to terminal, but candidate extraction is limited to remaining-turns proposal slots.',
                'Screened arms are sampled, so a non-hit is not a proof of absence.',
                'Optimal informative action is not proof of positive net value of information.',
                'All new samples are development; existing train/test corpora are untouched.'])
    (out/'fixtures.json').write_text(json.dumps(dict(fixtures=[k['fixture'] for k in kept],split='development'),indent=2)+'\n')
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    lines=['# 随机轨迹筛选漏斗','', '| 阶段 | 数量 |','|---|---:|']
    for k in ['structures','configurations','path_requests','trajectories_started','trajectories_finished','trajectory_failures','unique_decisions','verified_structures','retained']:
        lines.append(f'| {k} | {summary[k]} |')
    lines += ['', '状态：`'+json.dumps(summary['statuses'])+'`','', '验证失败阶段：`'+json.dumps(summary['failed_stages'])+'`','',
              '覆盖（类别可重叠）：`'+json.dumps(summary['coverage'])+'`','',
              '[完整配置和限制](summary.json) · [逐节点筛选](decisions.jsonl) · [生成事件](events.jsonl) · [保留样本](retained.jsonl)','',
              '每个 path request 可以尝试多个查询配置，因此不等于一条实际轨迹。普通对照保留；未完成验证不算筛选失败。下列限制阻止将结果直接解释为游戏本身缺少社会判断机会：','']
    lines += ['- '+x for x in summary['limits']]
    (out/'REPORT.md').write_text('\n'.join(lines)+'\n')
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-dir',type=Path,required=True);p.add_argument('--seed',type=int,default=97000)
    p.add_argument('--seeds',type=int,default=2);p.add_argument('--players',type=int,nargs='+',choices=[3,4,5],default=[3,4])
    p.add_argument('--hidden-goals',type=int,nargs='+',choices=[1,2],default=[1,2]);p.add_argument('--trajectories',type=int,default=2)
    p.add_argument('--actions',type=int,default=2);p.add_argument('--goals',type=int,default=7)
    p.add_argument('--query-sets',type=int,default=2);p.add_argument('--remaining-turns',type=int,default=3)
    p.add_argument('--max-nodes',type=int,default=1000);p.add_argument('--max-arms',type=int,default=8)
    p.add_argument('--seconds',type=float,default=90)
    args=p.parse_args()
    if not math.isfinite(args.seconds) or min(args.seeds,args.trajectories,args.actions,args.goals,args.query_sets,args.remaining_turns,args.max_nodes,args.max_arms,args.seconds)<=0:p.error('Budgets must be positive')
    print(json.dumps(run(args),indent=2))


if __name__=='__main__':main()
