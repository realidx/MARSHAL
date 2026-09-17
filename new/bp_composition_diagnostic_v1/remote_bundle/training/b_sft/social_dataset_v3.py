"""Regenerate fixed-query, evidence-qualified online development datasets.

No old static labels are copied. All new actions use the unchanged native game
and shared partner solver. Selection uses task/teacher properties, never LM scores.
"""
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path
import argparse
import hashlib
import json

from training.b_sft.online_social import OnlineSocial, VERSION
from training.b_sft.social_task import TASK_VERSION
from training.b_sft.social_cases import key, P_INSTRUCTION
from training.b_sft.social_holdout import topology_id
from training.b_sft.social_holdout_expand import read_rows, check_pack
from training.b_sft.social_lm_eval import load_pack
from training.b_sft.online_social_audit import verify
from benac_p.endgame_diagnose import decode_action

BUDGETS = dict(turns=2, max_nodes=10000, seconds=5)


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')


def lines(path, rows):
    path.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))


def qualification(env, values):
    counts=Counter()
    for event in env.events:
        if event.get('evidence'):
            counts.update({k:v for k,v in event['evidence']['exclusion_reasons'].items() if k!='retained'})
    if env.invalid_reason: basis='unavailable'
    elif counts['residual_native_order']: basis='native_order_sensitive'
    elif counts['prosocial_tie_rule']: basis='prosocial_rule_conditioned'
    elif counts['strict_self_value']: basis='strict_self_value'
    else: basis='no_exclusion'
    av=values.get('values') or []
    best=max((a['value'] for a in av),default=None)
    optimal=[a['action'] for a in av if abs(a['value']-best)<1e-8]
    spread=(best-min(a['value'] for a in av)) if av else None
    remaining=len(env.raw['game']['round_robin'])-env.node.state.turn_index
    actions=[a.to_dict() for a in env.game.rules.actions(env.node)]
    phase='response' if env.node.pending else 'proposal'
    response=('reject' if optimal==[{'response':'REJECT'}] else 'accept' if optimal==[{'response':'ACCEPT'}]
              else 'menu_choice' if phase=='response' and any(a.get('response','').startswith('CHOOSE') for a in optimal)
              else 'tie' if phase=='response' and av else None)
    return dict(B_basis=basis,B_aux_mask=not(env.invalid_reason or env.fragile),
        exclusion_counts=dict(counts),
        B_basis_scope='History-event classification under the declared frozen policy, not a policy-robust posterior.',
        P_basis=values.get('basis','unavailable'),P_aux_mask=bool(values['mask'] and spread>1e-8),
        P_value_spread=spread,P_optimal_actions=optimal,
        phase=phase,remaining_proposal_turns=remaining,response_target=response,
        menu_available=any(a.get('action')=='MENU' or a.get('response','').startswith('CHOOSE') for a in actions),
        P_scope=values.get('scope'),teacher_failure=env.invalid_reason)


def distribution(rows):
    qs=[r['supervision'] for r in rows]
    bs=[b for r in rows if r['teacher']['B_aux_mask'] for b in r['teacher']['B_by_target'] or []]
    return dict(decisions=len(rows),independent_topologies=len({r['topology'] for r in rows}),
        phase=dict(Counter(q['phase'] for q in qs)),
        response_targets=dict(Counter(q['response_target'] for q in qs if q['phase']=='response')),
        remaining_proposal_turns=dict(Counter(q['remaining_proposal_turns'] for q in qs)),
        menu_decisions=sum(q['menu_available'] for q in qs),
        nonterminal_decisions=sum(q['P_basis']=='reference_continuation' for q in qs),
        discriminating_P=sum(q['P_aux_mask'] for q in qs),
        B_supervision_basis=dict(Counter(q['B_basis'] for q in qs)),
        B_targets=len(bs),B_supports=dict(Counter('/'.join(b['answer']['possible_preferences']) for b in bs)),
        B_favored=dict(Counter(b['answer']['favored'] for b in bs)),
        by_topology=dict(Counter(r['topology'] for r in rows)))


def evidence_cohort(rows, per_topology=8):
    """Preserve informative B cases independently of P's terminal-control cap.

    Observing a partner often produces a response point. Removing those points
    merely because their own P is easy also removes the evidence B should learn.
    One no-exclusion control per topology keeps 'do not infer' represented.
    """
    groups=defaultdict(list)
    for r in rows:
        if r['teacher']['B_aux_mask']:groups[r['topology']].append(r)
    chosen=[]
    for _,rs in sorted(groups.items()):
        def features(r):
            return {(tuple(b['answer']['possible_preferences']),b['answer']['favored'])
                    for b in r['teacher']['B_by_target'] or []
                    if len(b['answer']['possible_preferences'])<3}
        info=[r for r in rs if features(r)];covered=set();local=[]
        while info and len(local)<per_topology:
            info.sort(key=lambda r:(-len(features(r)-covered),-len(features(r)),r['id']))
            r=info.pop(0);local.append(r);covered|=features(r)
        controls=sorted((r for r in rs if not features(r)),key=lambda r:r['id'])
        chosen.extend(local)
        if controls:chosen.append(controls[0])
    return chosen


class Builder:
    def __init__(self,out,split):
        if out.exists():raise ValueError('Use a new output directory')
        out.mkdir(parents=True);(out/'games').mkdir()
        self.out=out;self.split=split;self.rows={};self.traces=[];self.games={};self.roots=[];self.attempts=[]

    def record(self,env,source,setup):
        env.ensure_teacher();ctx=env.context();rid=source+'-'+key(ctx)
        if rid not in self.rows:
            values=env.p_reference_values(max_rollouts=2048,seconds=20)
            supervision=qualification(env,values)
            self.rows[rid]=dict(id=rid,source=source,setup=setup,split=self.split,
                topology=topology_id(env.raw),input=ctx,solver_budgets=env.budgets,
                teacher=dict(B_by_target=env.belief_table(),B_aux_mask=supervision['B_aux_mask'],P_reference=values),
                supervision=supervision)
        return rid

    def add(self,raw,prefix,setup,budgets=None,all_first_actions=False):
        raw=deepcopy(raw);raw['history']=[];raw.pop('teacher_model',None)
        source=raw['id'];self.games[source]=raw
        env=OnlineSocial(raw,prefix,**(budgets or BUDGETS));env.ensure_teacher()
        if env.invalid_reason:
            self.attempts.append(dict(source=source,setup=setup,status='unavailable',reason=env.invalid_reason));return
        if env.actor!=raw['ego']:
            # Partners before the next learner decision follow their actual policy.
            starts=[]
            for world in env.worlds:
                branch=env.fork()
                while not branch.terminal and branch.actor!=raw['ego']:
                    branch.step(branch.reference_action(world[branch.actor]),kind='partner')
                if not branch.terminal and not branch.invalid_reason:starts.append((branch,world))
        else:starts=[(env,world) for world in env.worlds]
        first_ids=set();before=len(self.rows)
        for start,world in starts:
            actions=start.game.rules.actions(start.node)
            # Cover response choices and both ends of OFFER/MENU groups, plus PASS.
            groups=defaultdict(list)
            for i,a in enumerate(actions):groups[a.to_dict().get('action','response')].append(i)
            indices=sorted({i for group in groups.values() for i in (group[0],group[-1])})
            if start.node.pending or all_first_actions:indices=list(range(len(actions)))
            for index in indices:
                run=start.fork();snapshots=[];first=True
                while not run.terminal:
                    if run.actor==raw['ego']:
                        rid=self.record(run,source,setup);snapshots.append(rid)
                        if first:first_ids.add(rid)
                        action=actions[index] if first else run.reference_action(world[run.actor])
                        first=False;run.step(action,kind='learner')
                    else:run.step(run.reference_action(world[run.actor]),kind='partner')
                self.traces.append(dict(source=source,setup=setup,first_action_index=index,
                    environment_world=world,snapshots=snapshots,history=run.history,events=run.events,
                    utilities=run.outcome(world),usable=not bool(run.invalid_reason),unavailable=run.invalid_reason))
        self.roots.extend(sorted(first_ids))
        self.attempts.append(dict(source=source,setup=setup,status='completed',new_points=len(self.rows)-before))
        lines(self.out/'screening.jsonl',self.attempts)
        print(json.dumps(self.attempts[-1]),flush=True)

    def migrate_online(self,pack):
        _,points=load_pack(pack)
        for point in points:
            source=point['row']['source'];raw=point['raw'];self.games[source]=raw
            env=OnlineSocial.replay_events(raw,point['events'],protocol=VERSION,**BUDGETS)
            rid=self.record(env,source,point['row']['setup'])
            if all(e['kind']=='setup' for e in point['events']):self.roots.append(rid)
        old=read_rows(pack/'trajectories.jsonl')
        lookup={(r['source'],json.dumps(r['input']['history'],sort_keys=True)):r['id'] for r in self.rows.values()}
        for trace in old:
            row=deepcopy(trace);row['snapshots']=[]
            for n in range(len(trace['history'])+1):
                rid=lookup.get((trace['source'],json.dumps(trace['history'][:n],sort_keys=True)))
                if rid:row['snapshots'].append(rid)
            self.traces.append(row)

    def finish(self,max_per_topology=18,*,selected=None,belief_selected=None,version='social-dataset-v3',extra_summary=None):
        pool=list(self.rows.values());by_topology=defaultdict(list)
        for r in pool:by_topology[r['topology']].append(r)
        chosen=[]
        for topology,rs in sorted(by_topology.items()):
            # Round-robin across semantic cohorts. Value ties and masked B are
            # retained as controls, but cannot swamp the planning/evidence cohort.
            cohorts=defaultdict(list)
            for r in sorted(rs,key=lambda r:r['id']):
                q=r['supervision']
                if not r['teacher']['P_reference']['mask']:cohort='unavailable_control'
                elif q['phase']=='proposal':cohort='proposal_menu' if q['menu_available'] else 'proposal'
                elif q['remaining_proposal_turns']>1:cohort='response_early_'+str(q['response_target'])
                else:cohort='response_terminal_'+str(q['response_target'])
                cohorts[cohort].append(r)
            local=[];covered=set()
            def features(r):
                if not r['teacher']['B_aux_mask']:return set()
                return {('B',tuple(b['answer']['possible_preferences']),b['answer']['favored'])
                        for b in r['teacher']['B_by_target'] or []}
            def priority(r):
                bs=r['teacher']['B_by_target'] or []
                informative=sum(len(b['answer']['possible_preferences'])<3 for b in bs) if r['teacher']['B_aux_mask'] else 0
                return (-len(features(r)-covered),-informative,
                        -int(r['supervision']['P_aux_mask']),r['id'])
            priorities=sorted(cohorts,key=lambda c:(c.startswith('response_terminal'),c=='unavailable_control',c))
            while len(local)<max_per_topology and any(cohorts.values()):
                for c in priorities:
                    if not cohorts[c] or len(local)>=max_per_topology:continue
                    terminal_count=sum(x['supervision']['P_basis']=='direct_terminal' for x in local)
                    if c.startswith('response_terminal') and terminal_count>=max(2,max_per_topology//4):
                        cohorts[c]=[];continue
                    if c=='unavailable_control' and any(x['supervision']['P_basis']=='unavailable' for x in local):
                        cohorts[c]=[];continue
                    cohorts[c].sort(key=priority)
                    row=cohorts[c].pop(0);local.append(row);covered|=features(row)
            chosen.extend(local)
        if selected is not None:chosen=selected
        b_chosen=evidence_cohort(pool) if belief_selected is None else belief_selected
        ids={r['id'] for r in chosen};pairs={}
        for trace in self.traces:
            for a,b in zip(trace['snapshots'],trace['snapshots'][1:]):
                if a not in ids or b not in ids:continue
                ra,rb=self.rows[a],self.rows[b]
                if not(ra['teacher']['B_aux_mask'] and rb['teacher']['B_aux_mask']):continue
                gold=lambda r:[(v['player'],v['goal'],v['answer']) for v in r['teacher']['B_by_target'] or []]
                pair=dict(before=a,after=b,category='maintain' if gold(ra)==gold(rb) else 'update')
                pairs[key(pair)]=pair
        checked_rows=list({r['id']:r for r in chosen+b_chosen}.values())
        verification=verify(self.games,checked_rows,self.traces)
        for source,raw in self.games.items():dump(self.out/'games'/f'{source}.json',dict(fixture=raw,topology=topology_id(raw)))
        lines(self.out/'questions.jsonl',chosen);lines(self.out/'all_candidates.jsonl',pool)
        lines(self.out/'B_evidence_questions.jsonl',b_chosen)
        lines(self.out/'screening.jsonl',self.attempts)
        lines(self.out/'trajectories.jsonl',self.traces);lines(self.out/'pairs.jsonl',list(pairs.values()))
        lines(self.out/'B_inputs.jsonl',[dict(id=r['id'],input=r['input']) for r in chosen])
        lines(self.out/'P_contexts.jsonl',[dict(id=r['id'],context=dict(r['input'],instruction=P_INSTRUCTION),
                                              belief_source='actual model B output required') for r in chosen])
        stats=distribution(chosen)
        summary=dict(version=version,protocol=VERSION,B_task_version=TASK_VERSION,
            split=self.split,**stats,root_questions=[r for r in dict.fromkeys(self.roots) if r in ids],
            candidate_distribution=distribution(pool),pairs=len(pairs),
            B_evidence_distribution=distribution(b_chosen),
            cohorts=dict(planning='questions.jsonl',belief='B_evidence_questions.jsonl'),
            pair_counts=dict(Counter(p['category'] for p in pairs.values())),verification=verification,
            actual_LM=False,model_based_selection=False,formal_training_ready=False,
            scope='Repaired online development material. No optimizer implementation or causal B-to-P experiment.',
            sampling='Deterministic semantic-cohort round-robin per topology, retaining diverse supported B sets/favored labels; terminal controls capped at one quarter per topology.',
            solver='Unchanged shared information-set partner algorithm; exact fixed-policy labels are assumption-conditioned.')
        if extra_summary:summary.update(extra_summary)
        dump(self.out/'summary.json',summary)
        report=['# 修复后的在线数据','',f"固定查询协议：{TASK_VERSION}。原始数据不变，教师标签在线重算。",'',
                '```json',json.dumps(stats,ensure_ascii=False,indent=2),'```','',
                'P 主样本见 questions.jsonl：限制简单终局题；B 主样本见 B_evidence_questions.jsonl：保留有证据的偏好判断，并保留每结构一条不应排除的对照。两组都使用全部固定查询。',
                '逐项监督依据见各题的 supervision；全部候选及完整轨迹保留，缺标签不填零。',
                '本包为开发数据；静态旧标签未复制，现有 B-only SFT 入口不消费本包。']
        (self.out/'REVIEW.md').write_text('\n'.join(report)+'\n')
        dump(self.out/'checksums.json',{str(p.relative_to(self.out)):hashlib.sha256(p.read_bytes()).hexdigest()
                                     for p in self.out.rglob('*') if p.is_file()})
        return summary


def expanded_setups(raw):
    """Public interventions; their offers are never inverted as partner evidence."""
    raw=deepcopy(raw);raw['history']=[];raw.pop('teacher_model',None)
    raw['game']['menu_enabled']=True
    order=raw['game']['round_robin'];ego=raw['ego']
    for remaining in (3,4):
        if len(order)<remaining:continue
        r=deepcopy(raw);pos=len(order)-remaining
        start=pos//raw['game']['n_players']*raw['game']['n_players']
        where=next(i for i in range(start,start+raw['game']['n_players']) if order[i]==ego)
        r['game']['round_robin'][pos],r['game']['round_robin'][where]=r['game']['round_robin'][where],r['game']['round_robin'][pos]
        r['id']=raw['id']+f'-menu-r{remaining}'
        prefix=[dict(action='PASS') for _ in range(pos)]
        yield r,prefix,f'menu_remaining_{remaining}'
    # Seed response challenges at early and final turns, covering both own
    # positive and negative immediate effects. Labels still use full continuation.
    for remaining in (1,3):
        if len(order)<remaining:continue
        r=deepcopy(raw);pos=len(order)-remaining
        partner=next(p for p in range(r['game']['n_players']) if p!=ego)
        start=pos//r['game']['n_players']*r['game']['n_players']
        where=next(i for i in range(start,start+r['game']['n_players']) if order[i]==partner)
        r['game']['round_robin'][pos],r['game']['round_robin'][where]=r['game']['round_robin'][where],r['game']['round_robin'][pos]
        r['id']=raw['id']+f'-response-r{remaining}'
        prefix=[dict(action='PASS') for _ in range(pos)]
        env=OnlineSocial(r,prefix,**BUDGETS);offers=[a.to_dict() for a in env.game.rules.actions(env.node)
                        if a.to_dict().get('action')=='OFFER' and a.to_dict()['partner_id']==ego]
        buckets={}
        for a in offers:
            pending=env.game.rules._apply(env.node,decode_action(a))
            accepted=env.game.rules._apply(pending,decode_action({'response':'ACCEPT'}))
            sat=accepted.state.goal_satisfaction()
            value=sum(x*y for x,y in zip(sat,r['own_preferences']))
            sign='negative' if value<0 else 'positive' if value>0 else 'zero'
            buckets.setdefault(sign,a)
        for sign,a in buckets.items():yield r,prefix+[a],f'public_offer_{sign}_r{remaining}'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--kind',choices=['cases','generalization'],required=True)
    p.add_argument('--resample-from',type=Path,help='Re-select an already verified v3 candidate pool without recomputing labels')
    p.add_argument('--old-cases',type=Path,default=Path('new/local_data/social_cases_v2'))
    p.add_argument('--old-generalization',type=Path,default=Path('new/local_data/social_generalization_v2'))
    args=p.parse_args();builder=Builder(args.output_dir,'development' if args.kind=='cases' else 'development_generalization')
    if args.resample_from:
        check_pack(args.resample_from)
        builder.rows={r['id']:r for r in read_rows(args.resample_from/'all_candidates.jsonl')}
        builder.traces=read_rows(args.resample_from/'trajectories.jsonl')
        builder.games={p.stem:json.loads(p.read_text())['fixture'] for p in (args.resample_from/'games').glob('*.json')}
        builder.roots=list(dict.fromkeys(t['snapshots'][0] for t in builder.traces if t['snapshots']))
        builder.attempts=read_rows(args.resample_from/'screening.jsonl')
        lines(builder.out/'screening.jsonl',builder.attempts)
        print(json.dumps(builder.finish(),ensure_ascii=False,indent=2));return
    check_pack(args.old_cases);check_pack(args.old_generalization)
    if args.kind=='generalization':
        builder.migrate_online(args.old_generalization)
        raws=[json.loads(p.read_text())['fixture'] for p in sorted((args.old_generalization/'games').glob('*.json'))]
        # Small action spaces permit unchanged MENU enumeration and longer online
        # continuations without shrinking the legal action set.
        raws=[r for r in raws if max(r['game']['n_actions_per_player'])==1]
        for raw in raws:
            for r,prefix,setup in expanded_setups(raw):builder.add(r,prefix,setup)
    else:
        for path in sorted((args.old_cases/'games').glob('*.json')):
            case=json.loads(path.read_text())
            if 'episodes' not in case:continue  # Uncertified authored long routes stay excluded.
            raw=case['fixture'];raw['id']=path.stem
            builder.add(raw,case.get('prefix',[]),'regenerated_online')
            if max(raw['game']['n_actions_per_player'])==1:
                for r,prefix,setup in expanded_setups(raw):builder.add(r,prefix,setup)
    result=builder.finish();print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
