"""Assemble replayed native datasets under one schema; preserve all source splits."""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from training.b_sft.structure_audit import structure_id, digest
from training.b_sft.social_rollout import build, queries_for, belief_payload, run_episode, scripted_agent
from training.b_sft.favored_belief import marginal
from training.b_sft.dataset_review import family_id, timeline, conservative_b_masks
from training.b_sft.evidence_switch import decision_key
from benac_p.endgame_diagnose import decode_action

VERSION='social-dataset-reviewed-v2'


def record_id(raw):
    return 'decision-'+digest(dict(structure=structure_id(raw),ego=raw['ego'],
        own=raw['own_preferences'],types=raw['type_catalogues'],history=raw.get('history',[])))[:24]


def reference_episode(raw,budget):
    """Teacher demonstration; never claim these are on-policy LM trajectories."""
    search,_,types,_=build(raw,budget)
    def agent(phase,payload):
        node=search.replay([decode_action(a) for a in payload['history']])
        if phase=='B':
            return dict(text='',answer=[dict(**q,**marginal(node.worlds,q['player'],q['goal'])['answer']) for q in queries_for(types,search.ego)])
        q=search.q_values(node)
        return dict(text='',answer=max(q,key=lambda av:av[1])[0].to_dict())
    return run_episode(raw,agent,max_nodes=budget)


def validate(records,gold,links,games):
    ids={r['id']:r for r in records};labels={g['id']:g for g in gold}
    if len(ids)!=len(records) or len(labels)!=len(gold) or set(ids)!=set(labels):raise ValueError('Duplicate/missing decisions or gold')
    splits={};families={}
    scenarios={g['id']:g for g in games}
    for game in games:
        previous=splits.setdefault(game['source_id'],game['split'])
        if previous!=game['split']:raise ValueError('Structure crosses splits')
        family=game.get('family_id',game['source_id'])
        if families.setdefault(family,game['split'])!=game['split']:raise ValueError('Isomorphic family crosses splits')
    for r in records:
        if splits[r['source_id']]!=r['split']:raise ValueError('Decision crosses split')
        if any(k in r['input'] for k in ['teacher_counts','q','gold','optimal_actions','actual_world']):raise ValueError('Teacher leakage')
        if r['planning_belief_source']!='runtime_model':raise ValueError('P must use model B')
        game=scenarios[r['scenario_id']]
        types={int(p):tuple(tuple(row) for row in rs) for p,rs in game['public_type_catalogues'].items()}
        if r['input']['queries']!=queries_for(types,game['ego']):raise ValueError('Query schedule changed')
        g=labels[r['id']]
        if [(b['player'],b['goal']) for b in g['B']]!=[(q['player'],q['goal']) for q in r['input']['queries']]:raise ValueError('Missing B label')
        expected_masks=conservative_b_masks(g['evidence_audit'],r['input']['queries'])
        if g['B_auxiliary_masks']!=expected_masks:raise ValueError('B auxiliary masks mismatch')
        if g['P']['available']:
            if r['terminal'] or [a['action'] for a in g['P']['actions']]!=r['input']['legal_actions']:raise ValueError('P actions mismatch')
            best=max(a['q'] for a in g['P']['actions'])
            opt=[a['action'] for a in g['P']['actions'] if best-a['q']<=1e-9]
            if opt!=g['P']['optimal_actions']:raise ValueError('P optimum mismatch')
            spread=best-min(a['q'] for a in g['P']['actions'])
            if g['P'].get('auxiliary_mask')!=(spread>1e-9):raise ValueError('P auxiliary mask mismatch')
    for l in links:
        if l['left'] not in ids or l['right'] not in ids:raise ValueError('Dangling link')
        a,b=ids[l['left']],ids[l['right']]
        if (a['source_id'],a['split'])!=(b['source_id'],b['split']):raise ValueError('Link crosses game/split')
        if l['kind']=='temporal':
            if a['scenario_id']!=b['scenario_id']:raise ValueError('Temporal link changes scenario')
            if b['history'][:len(a['history'])]!=a['history'] or len(b['history'])<=len(a['history']):raise ValueError('Temporal link does not extend history')
        elif l.get('contrast_type')=='own_goal_switch':
            ga,gb=labels[a['id']],labels[b['id']]
            if a['history']!=b['history'] or ga['physical_key']!=gb['physical_key'] or ga['partner_posterior_id']!=gb['partner_posterior_id']:
                raise ValueError('Own-goal contrast changes evidence or partner posterior')
            if ga['B']!=gb['B']:raise ValueError('Own-goal contrast changes B')
            if not ga['P']['available'] or not gb['P']['available'] or any(x in gb['P']['optimal_actions'] for x in ga['P']['optimal_actions']):
                raise ValueError('Own-goal contrast does not require action switch')
        elif l.get('contrast_type')=='evidence_action_switch':
            ga,gb=labels[a['id']],labels[b['id']]
            if a['scenario_id']!=b['scenario_id'] or ga['physical_key']!=gb['physical_key'] or ga['partner_posterior_id']==gb['partner_posterior_id']:
                raise ValueError('Not a matched physical state evidence contrast')
            if not ga['P']['available'] or not gb['P']['available'] or any(x in gb['P']['optimal_actions'] for x in ga['P']['optimal_actions']):
                raise ValueError('Evidence contrast does not require action switch')


def write_reports(out):
    def rows(name):return [json.loads(l) for l in (out/name).read_text().splitlines()]
    summary=json.loads((out/'summary.json').read_text());records=rows('decisions.jsonl')
    games=rows('games.jsonl');gold={g['id']:g for g in rows('gold.jsonl')};links=rows('links.jsonl')
    lines=['# 统一开发数据集','',
           '当前数据与监督约定见 [README.md](../../../training/b_sft/README.md#teacher-and-supervision)；历史逐局审查已归档。[cohorts.json](cohorts.json) 是可重叠诊断分组。使用局部奖励时须读取教师侧 B_auxiliary_masks 与 P.auxiliary_mask。','',
           '已统一并重放，不表示正式训练就绪。轨迹的 policy 字段区分参考教师和固定流程探针；都不是 LM on-policy 轨迹。','',
           f"{summary['structures']} 个精确结构，{summary['scenarios']} 个角色/先验场景，{summary['decisions']} 个决策记录（含终局诊断）。",'',
           '| split | 结构数 | 决策记录数 |','|---|---:|---:|']
    lines += [f"| {split} | {v['structures']} | {v['decisions']} |" for split,v in summary['splits'].items()]
    lines += ['','## 文件入口','',
              '- [实例逐项对照](EXAMPLES.md)：同集合倾向差异、证据导致行动切换、完整参考 episode。',
              '- [games.jsonl](games.jsonl)：原生规则、角色、自身目标和公开候选目录。',
              '- [decisions.jsonl](decisions.jsonl)：统一模型可见输入；P 的 B 由运行时模型提供。',
              '- [gold.jsonl](gold.jsonl)：全量 B set/favored、原生 P 动作与终局参考 Q，独立教师侧文件。',
              '- [links.jsonl](links.jsonl)：temporal / contrast 明确分开；每个查询分别标记集合和倾向变化。',
              '- [episodes.jsonl](episodes.jsonl)：train/development 起点的完整参考教师轨迹及真实终局结果。',
              '- [summary.json](summary.json)、[exclusions.jsonl](exclusions.jsonl)：覆盖、来源和显式缺失。', '',
              '## 尚缺的内容','']+['- '+x for x in summary['gaps']]
    lines += ['','## 游戏清单','', '| source | 玩家数 | split | 场景数 | 决策数 |','|---|---:|---|---:|---:|']
    for source in sorted({g['source_id'] for g in games}):
        gs=[g for g in games if g['source_id']==source];rs=[r for r in records if r['source_id']==source]
        lines.append(f"| {source} | {gs[0]['game']['n_players']} | {gs[0]['split']} | {len(gs)} | {len(rs)} |")
    (out/'REPORT.md').write_text('\n'.join(lines)+'\n')
    example=['# 实例检查','', '所有 Q/判断来自声明的参考教师；不代表模型已学会。计数只在教师侧。']
    by_id={r['id']:r for r in records}
    for link in links:
        if link['kind']!='contrast':continue
        example += ['', '## 跨历史对照', '', '来源：`'+link['origin']+'`。这两段历史不是同一局先后发生的更新。']
        for side in ('left','right'):
            r=by_id[link[side]];g=gold[r['id']]
            example += ['', '### '+side, '', '决策 ID：`'+r['id']+'`', '',
                        '公开历史：', '```json',json.dumps(r['history'],ensure_ascii=False,indent=2),'```','',
                        '全量 B 教师答案：','```json',json.dumps([dict(player=b['player'],goal=b['goal'],**b['answer']) for b in g['B']],ensure_ascii=False,indent=2),'```','',
                        '原生 P 的参考 Q / 全部最优动作：','```json',json.dumps(g['P'],ensure_ascii=False,indent=2),'```']
    episodes=rows('episodes.jsonl')
    complete=[e for e in episodes if e['trajectory']['status']=='terminal']
    if complete:
        e=complete[-1];t=e['trajectory']
        example += ['', '## 一条完整环境轨迹','', '起点：`'+e['start_decision']+'`；策略：`'+e['policy']+'`，不是 LM rollout。', '',
                    f"真实终局效用 {t['terminal_utility']}；归一化回报 {t['normalized_return']}。",'']
        for i,c in enumerate(t['calls']):
            example += [f"### 调用 {i+1}：{c['phase']}",'','当时可见行动历史：','```json',json.dumps(c['input']['history'],ensure_ascii=False,indent=2),'```','',
                        '该策略输出：','```json',json.dumps(c['output'],ensure_ascii=False,indent=2),'```','']
    (out/'EXAMPLES.md').write_text('\n'.join(example)+'\n')


def write_cohorts(out):
    def rows(f):return [json.loads(l) for l in (out/f).read_text().splitlines()]
    records=rows('decisions.jsonl');gold={g['id']:g for g in rows('gold.jsonl')};links=rows('links.jsonl')
    def clean(key):return all(m['set_mask'] and m['favored_mask'] for m in gold[key]['B_auxiliary_masks'])
    cohorts=dict(
        B_no_local_tie_flag=[r['id'] for r in records if r['allowed_tasks'] and clean(r['id'])],
        B_declared_policy_diagnostic=[r['id'] for r in records if r['allowed_tasks'] and not clean(r['id'])],
        P_value_choice=[r['id'] for r in records if gold[r['id']]['P']['auxiliary_mask']],
        P_equal_value_control=[r['id'] for r in records if gold[r['id']]['P']['available'] and not gold[r['id']]['P']['auxiliary_mask']],
        P_teacher_unavailable=[r['id'] for r in records if r['allowed_tasks'] and not gold[r['id']]['P']['available']],
        own_goal_switch_pairs=[[l['left'],l['right']] for l in links if l.get('contrast_type')=='own_goal_switch'],
        evidence_action_switch_without_local_tie_flag=[[l['left'],l['right']] for l in links if l.get('contrast_type')=='evidence_action_switch' and clean(l['left']) and clean(l['right'])])
    (out/'cohorts.json').write_text(json.dumps(dict(training_ready=False,
        note='Overlapping diagnostic lists, not sampling weights. No local tie flag does not prove robustness to unknown policies.',cohorts=cohorts),indent=2)+'\n')
    return {k:len(v) for k,v in cohorts.items()}


def assemble(corpora,witnesses,out,budget=3000,fixture_packs=()):
    if out.exists():raise ValueError('Output exists; choose a new directory')
    out.mkdir(parents=True)
    pending={};links=[];roots=[];protocol_roots=[];origins=[];source_splits={};family_splits={}
    def add(raw,split,origin):
        source=structure_id(raw)
        family=family_id(raw)
        if family_splits.setdefault(family,split)!=split:raise ValueError('Isomorphic family crosses splits; preserve held-out families')
        if source_splits.setdefault(source,split)!=split:raise ValueError('Structure crosses splits; do not silently promote held-out data')
        key=record_id(raw)
        if key not in pending:pending[key]=dict(raw=deepcopy(raw),split=split,source_id=source,family_id=family,origins=[])
        pending[key]['origins'].append(origin)
        return key
    for corpus in corpora:
        certs=[json.loads(l) for l in (corpus/'certificates.jsonl').read_text().splitlines()]
        branch_rows=[]
        for p in sorted(corpus.glob('*_links.jsonl')):branch_rows += [json.loads(l) for l in p.read_text().splitlines()]
        for c in certs:
            raw=c['fixture'];left=add(raw,c['split'],str(corpus)+':'+c['root_decision_id']);roots.append(left)
            for l in branch_rows:
                if l['root_decision_id']!=c['root_decision_id']:continue
                child=deepcopy(raw);child['history']=raw.get('history',[])+[l['branch_action']]+[e['action'] for e in l['evidence']]
                right=add(child,c['split'],str(corpus)+':branch:'+l['id'])
                links.append(dict(kind='temporal',left=left,right=right,action=l['branch_action'],evidence=l['evidence']))
        origins.append(dict(path=str(corpus),sha256=hashlib.sha256((corpus/'certificates.jsonl').read_bytes()).hexdigest()))
    for path in witnesses:
        w=json.loads(path.read_text());raw=w['fixture'];pair=[]
        for side in ['left','right']:
            r=deepcopy(raw);r['history']=w[side]['history'];pair.append(add(r,'development',str(path)+':'+side))
        roots.append(add(raw,'development',str(path)+':episode_start'))
        links.append(dict(kind='contrast',left=pair[0],right=pair[1],origin=str(path),
                          contrast_type='favored_contrast' if 'robustness_ratio' in w else 'evidence_action_switch',
                          note='Alternative histories, not a temporal belief update.'))
        origins.append(dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    for path in fixture_packs:
        pack=json.loads(path.read_text());ids={}
        for raw in pack['fixtures']:
            if raw['id'] in ids:raise ValueError('Duplicate fixture ID in pack')
            ids[raw['id']]=add(raw,pack.get('split','development'),str(path)+':'+raw['id'])
        for link in pack.get('links',[]):
            links.append(dict(link,left=ids[link['left']],right=ids[link['right']],origin=str(path)))
        roots.extend(ids[k] for k in pack.get('episode_starts',[]))
        protocol_roots.extend(ids[k] for k in pack.get('protocol_episode_starts',[]))
        origins.append(dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    records=[];gold=[];games=[];failures=[];lookup={}
    for key,item in pending.items():
        raw=item['raw'];game_id='scenario-'+digest(dict(source=item['source_id'],ego=raw['ego'],own=raw['own_preferences'],types=raw['type_catalogues']))[:24]
        games.append(dict(id=game_id,source_id=item['source_id'],family_id=item['family_id'],split=item['split'],game=raw['game'],ego=raw['ego'],
                          own_preferences=raw['own_preferences'],public_type_catalogues=raw['type_catalogues']))
        try:
            search,node,types,partner=build(raw,budget);queries=queries_for(types,search.ego)
            payload=belief_payload(search,node,types,partner,raw.get('history',[]),queries,1.25)
            terminal=node.state.is_terminal
            ego_decision=not terminal and search.actor(node)==search.ego
            payload['legal_actions']=[a.to_dict() for a in search.actions(node)] if ego_decision else []
            r=dict(id=key,source_id=item['source_id'],scenario_id=game_id,split=item['split'],
                   history=raw.get('history',[]),terminal=terminal,input=payload,planning_belief_source='runtime_model',
                   allowed_tasks=['B','P'] if ego_decision else [],actor=search.actor(node),origins=item['origins'])
            b=[dict(**q,**marginal(node.worlds,q['player'],q['goal'])) for q in queries]
            evidence_audit=timeline(raw,budget)
            b_masks=conservative_b_masks(evidence_audit,queries)
            p=dict(available=False,auxiliary_mask=False,reason='terminal' if terminal else 'environment_prefix' if not ego_decision else None)
            if ego_decision:
                try:
                    q=search.q_values(node);best=max(v for _,v in q)
                    p=dict(available=True,actions=[dict(action=a.to_dict(),q=v) for a,v in q],
                           action_value_range=best-min(v for _,v in q),auxiliary_mask=best-min(v for _,v in q)>1e-9,
                           optimal_actions=[a.to_dict() for a,v in q if best-v<=1e-9],
                           semantics='Expected terminal utility under declared reference continuation, not actual outcome')
                except (RuntimeError,ValueError) as exc:p['reason']=f'{type(exc).__name__}: {exc}'
            records.append(r);gold.append(dict(id=key,B=b,P=p,physical_key=decision_key(node),
                B_auxiliary_masks=b_masks,
                B_mask_scope='Conservative component masks for any prior local tie-sensitive B update; exact fixed-policy answers are preserved. Later evidence does not re-enable a masked component.',
                evidence_audit=evidence_audit,
                partner_posterior_id=digest(sorted(tuple(row for p,row in enumerate(w) if p!=search.ego) for w in node.worlds)),
                terminal_utility=search.utility(node) if terminal else None))
            lookup[key]=gold[-1]
        except (RuntimeError,ValueError) as exc:
            failures.append(dict(id=key,stage='replay',reason=f'{type(exc).__name__}: {exc}'))
        print(json.dumps(dict(decision=key,done=len(records),failed=len(failures))),flush=True)
    # Exclusions are explicit, and links involving excluded nodes are logged.
    valid=[]
    for l in links:
        if l['left'] not in lookup or l['right'] not in lookup:
            failures.append(dict(stage='link',link=l,reason='Endpoint unavailable'));continue
        a=lookup[l['left']]['B'];b=lookup[l['right']]['B']
        if [(x['player'],x['goal']) for x in a]!=[(x['player'],x['goal']) for x in b]:raise ValueError('Query schedule changed')
        l['judgment_changes']=[dict(player=x['player'],goal=x['goal'],
            set_changed=x['answer']['possible_preferences']!=y['answer']['possible_preferences'],
            favored_changed=x['answer']['favored']!=y['answer']['favored']) for x,y in zip(a,b)]
        valid.append(l)
    present={r['scenario_id'] for r in records}
    games=list({g['id']:g for g in games if g['id'] in present}.values())
    validate(records,gold,valid,games)
    episodes=[]
    for key,policy in dict.fromkeys([(k,'reference_teacher_not_LM') for k in roots]+[(k,'scripted_protocol_probe_not_LM') for k in protocol_roots]):
        if key not in lookup:continue
        item=pending[key]
        # Evaluation partitions are packaged but never used to choose training trajectories.
        if item['split'] not in ('train','development'):continue
        try:r=reference_episode(item['raw'],budget) if policy=='reference_teacher_not_LM' else run_episode(item['raw'],scripted_agent,max_nodes=budget)
        except (RuntimeError,ValueError) as exc:r=dict(status='unavailable',error=str(exc),terminal_utility=None)
        episodes.append(dict(start_decision=key,source_id=item['source_id'],split=item['split'],
                             policy=policy,trajectory=r))
        print(json.dumps(dict(episode=key,status=r['status'])),flush=True)
    def jsonl(name,rows):(out/name).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
    for name,rows in [('games.jsonl',games),('decisions.jsonl',records),('gold.jsonl',gold),('links.jsonl',valid),('episodes.jsonl',episodes),('exclusions.jsonl',failures)]:jsonl(name,rows)
    for split in sorted({r['split'] for r in records}):
        jsonl(split+'_decisions.jsonl',[r for r in records if r['split']==split])
    summary=dict(version=VERSION,structures=len({g['source_id'] for g in games}),families=len({g['family_id'] for g in games}),scenarios=len(games),decisions=len(records),
        splits={s:dict(structures=len({r['source_id'] for r in records if r['split']==s}),decisions=sum(r['split']==s for r in records)) for s in sorted({r['split'] for r in records})},
        terminal_decisions=sum(r['terminal'] for r in records),p_teacher_available=sum(g['P']['available'] for g in gold),
        p_auxiliary_active=sum(g['P']['auxiliary_mask'] for g in gold),
        B_masked_components=dict(set=sum(not m['set_mask'] for r in records if r['allowed_tasks'] for m in lookup[r['id']]['B_auxiliary_masks']),
                                favored=sum(not m['favored_mask'] for r in records if r['allowed_tasks'] for m in lookup[r['id']]['B_auxiliary_masks'])),
        environment_prefixes=sum(not r['terminal'] and not r['allowed_tasks'] for r in records),
        nonterminal_B_answers=dict(Counter('|'.join(b['answer']['possible_preferences'])+':'+b['answer']['favored'] for r in records if r['allowed_tasks'] for b in lookup[r['id']]['B'])),
        multiple_hidden_partners=sum(len({q['player'] for q in r['input']['queries']})>1 for r in records if r['allowed_tasks']),
        contrast_types=dict(Counter(l.get('contrast_type','unspecified') for l in valid if l['kind']=='contrast')),
        query_counts=dict(Counter(len(r['input']['queries']) for r in records)),
        links=dict(Counter(l['kind'] for l in valid)),
        temporal_changes=dict(Counter('update' if c['set_changed'] or c['favored_changed'] else 'maintain' for l in valid if l['kind']=='temporal' for c in l['judgment_changes'])),
        episodes=dict(Counter(e['trajectory']['status'] for e in episodes)),exclusions=len(failures),training_ready=False,
        gaps=['No verified positive net information value cohort',
              'Binary reference only; no linear goals; fixed known partner policy and independent uniform catalogues',
              'No isolated causal planning gain from favored','Structural families guard renaming leakage; they do not certify behavioral equivalence',
              'Inspected development data does not replace an untouched evaluation set',
              'No LM on-policy trajectories, advantages or PPO batches'],origins=origins)
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    summary['cohort_counts']=write_cohorts(out)
    if not summary['cohort_counts']['evidence_action_switch_without_local_tie_flag']:
        summary['gaps'].insert(0,'No matched-state evidence/action-switch pair without local tie-sensitive B updates')
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    write_reports(out)
    (out/'checksums.json').write_text(json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.is_file()},indent=2)+'\n')
    (out/'READY.json').write_text(json.dumps(dict(assembled=True,validated=True,training_ready=False))+'\n')
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--corpus',type=Path,nargs='*',default=[]);p.add_argument('--witness',type=Path,nargs='*',default=[])
    p.add_argument('--fixtures',type=Path,nargs='*',default=[])
    p.add_argument('--output-dir',type=Path,required=True);p.add_argument('--max-nodes',type=int,default=3000)
    args=p.parse_args()
    if args.max_nodes<1:p.error('max-nodes must be positive')
    if not (args.corpus or args.witness or args.fixtures):p.error('Provide corpus, witness or fixtures')
    print(json.dumps(assemble(args.corpus,args.witness,args.output_dir,args.max_nodes,args.fixtures),indent=2))


if __name__=='__main__':main()
