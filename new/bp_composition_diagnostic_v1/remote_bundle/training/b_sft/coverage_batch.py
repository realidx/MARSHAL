"""Small stratified random-game review batch, including multi-partner uncertainty.

Each worker job has a hard process timeout; partial completed records survive.
No existing train/test data is modified. This is development mining, not training.
"""
import argparse
from collections import Counter
from dataclasses import replace
from itertools import combinations,product
import json
import math
from pathlib import Path
import random
import subprocess
import sys
import time

from training.b_sft.random_funnel import screen,digest,structure_id
from training.b_sft.social_rollout import build,queries_for
from training.b_sft.catalogues import validate_catalogues
from benac_p.generator import GeneratorConfig,generate_game


def make_game(seed,n,k,g,mode):
    spec=replace(generate_game(seed,GeneratorConfig(n_players=n,actions_per_player=k,n_goals=g,n_rounds=2)),menu_enabled=True)
    rng=random.Random(seed+777);ego=seed%n;others=[p for p in range(n) if p!=ego]
    rng.shuffle(others);targets=others[:2] if mode=='multi_partner' else others[:1]
    width=2 if mode=='multi_goal' else 1
    rows=[list(map(int,row)) for row in spec.private_preferences];types={str(p):[row] for p,row in enumerate(rows)};hidden=[]
    for target in targets:
        eligible=[goal.goal_id for goal in spec.goals if any(a.player_id==target for a in goal.required_actions)]
        choices=[gs for gs in combinations(eligible,width) if any(v==1 for i,v in enumerate(rows[target]) if i not in gs)
                 and all(any(rows[p][g]!=0 for p in range(n) if p!=target) for g in gs)]
        if not choices:raise ValueError('No valid hidden dimensions with a fixed positive preference')
        goals=rng.choice(choices)
        types[str(target)]=[[dict(zip(goals,vs)).get(i,v) for i,v in enumerate(rows[target])] for vs in product((1,0,-1),repeat=width)]
        hidden += [dict(player=target,goal=goal) for goal in goals]
    raw=dict(id=f'coverage-{seed}-{n}-{k}-{g}-{mode}',game=spec.to_dict(include_private=False),ego=ego,
        own_preferences=rows[ego],type_catalogues=types,history=[],hidden_dimensions=hidden,
        source=dict(seed=seed,mode=mode,generator='native random game; independent uniform hidden catalogues'))
    validate_catalogues(raw)
    return raw,tuple(tuple(row) for row in rows)


def read_complete(path):
    if not path.exists():return []
    text=path.read_text(errors='replace');lines=text.splitlines();rows=[]
    for i,line in enumerate(lines):
        try:rows.append(json.loads(line))
        except json.JSONDecodeError:
            if i!=len(lines)-1 or text.endswith('\n'):raise
            # A killed worker may leave a partial last write. Never treat it as
            # a completed record. Job status still records the timeout.
    return rows


def action_text(a):
    if 'response' in a:return a['response']
    if a.get('action')=='PASS':return 'PASS'
    def offer(o):return f"对 P{o['partner_id']}：自己→{o['proposer_action']}，对方→{o['partner_action']}"
    if a.get('action')=='MENU':return 'MENU；'+'；'.join(f"选项{i+1} {offer(o)}" for i,o in enumerate(a['offers']))
    return 'OFFER '+offer(a)


def write_review(out,chosen):
    lines=['# 按游戏审查','', '均为随机生成后的开发候选；没有进行 LM 训练。每个结构展示一个代表性决策点。向量表示提案执行后的 commitment，不是新增量；完整数据保留在 review_selection.json。']
    for i,c in enumerate(chosen):
        r=max(c['records'],key=lambda r:(r['screen']['status']=='verified',len(r['screen']['categories']),r['mode']=='multi_partner'))
        f=r['fixture'];s=r['screen'];g=f['game']
        lines += ['',f'## 游戏 {i+1}：{c["source"]}','',
                  f"{g['n_players']} 人，每人 {g['n_actions_per_player'][0]} 个 commitment，{len(g['goals'])} 个 goal。角色 P{f['ego']}；隐藏方式 {r['mode']}。",'',
                  '本结构新增覆盖：'+', '.join(c['new_coverage'])+'。','',
                  '### 规则与自身目标','', '| goal | 完成要求 | 自身偏好 |','|---|---|---:|']
        for goal,w in zip(g['goals'],f['own_preferences']):
            req=', '.join(f"P{a['player_id']}.A{a['action_id']}" for a in goal['required_actions'])
            lines.append(f"| G{goal['goal_id']} | {req} | {w} |")
        hidden=f.get('hidden_dimensions') or queries_for({int(p):rs for p,rs in f['type_catalogues'].items()},f['ego'])
        lines += ['', '隐藏维度：'+', '.join(f"P{q['player']}.G{q['goal']}" for q in hidden)+'。','',
                  '### 已发生的公开历史','', '| 事件 | 玩家 | 动作 |','|---|---|---|']
        base=dict(f,history=[]);search,node,_,_=build(base,1000)
        from benac_p.endgame_diagnose import decode_action
        for j,a in enumerate(f['history']):
            lines.append(f"| {j+1} | P{search.actor(node)} | {action_text(a)} |")
            node=search._apply(node,decode_action(a))
        lines += ['', '### 当前全量 B 教师判断','', '| 玩家/goal | 可能集合 | favored |','|---|---|---|']
        for b in s.get('B',[]):lines.append(f"| P{b['player']}.G{b['goal']} | {', '.join(b['possible_preferences'])} | {b['favored']} |")
        lines += ['', '### 后续机会与参考价值','', '分类：'+', '.join(s['categories'])+'。','']
        arms=[a for a in s.get('arms',[]) if any(not b['terminal'] and b['after_B']!=s.get('B') for b in a['branches'])]
        if not arms:lines+=['本节点作为普通对照；抽样行动中未找到仍有后续决策的信息分支，不表示遍历证明没有。']
        for a in arms[:2]:
            lines += ['- 考察动作：'+action_text(a['action'])+f"；参考 regret={a.get('root_regret','未计算')}。",'']
            for b in a['branches']:
                events=' → '.join(f"P{e['player_id']} {action_text(e['action'])}" for e in b['evidence'])
                after='；'.join(f"P{x['player']}.G{x['goal']}={','.join(x['possible_preferences'])}，favored={x['favored']}" for x in b['after_B'])
                lines += ['  - 公开响应：'+(events or '无')+'。', '  - 后 B：'+after+('；已终局。' if b['terminal'] else '；仍有后续决策。'),'']
        if 'Q' in s:
            best=max(x['value'] for x in s['Q']);opts=[x for x in s['Q'] if best-x['value']<=1e-9]
            lines += [f"参考最优 Q={best}，共 {len(opts)} 个并列最优动作，最多列 3 个：",'']
            lines += ['- '+action_text(x['action']) for x in opts[:3]]
        lines += ['', '审查重点：判断是否确由上述公开证据支持？是否还有机会利用信息？信息行动的价值可能来自 commitment 本身，不能直接等同于信息净价值。']
    (out/'REVIEW.md').write_text('\n'.join(lines)+'\n')


def worker(job,out):
    def save(name,obj):
        with (out/name).open('a') as f:f.write(json.dumps(obj)+'\n');f.flush()
    try:raw,world=make_game(job['seed'],job['n'],job['k'],job['g'],job['mode'])
    except (RuntimeError,ValueError) as exc:save('events.jsonl',dict(event='configuration_unavailable',reason=str(exc)));return
    (out/'game.json').write_text(json.dumps(raw,indent=2)+'\n')
    seen=set()
    for path in range(job['paths']):
        save('events.jsonl',dict(event='path_started',path=path));history=[];index=0
        try:
            s,node,_,_=build(raw,job['nodes']);rng=random.Random(job['seed']+path*100000007)
            while not node.state.is_terminal:
                actor=s.actor(node)
                if actor==s.ego:
                    if len(s.spec.round_robin)-node.state.turn_index<=job['remaining']:
                        fixture=dict(raw,id=raw['id']+f'-p{path}-d{index}',history=history[:])
                        key=digest(history)
                        if key not in seen:
                            seen.add(key);save('events.jsonl',dict(event='screen_started',id=fixture['id']))
                            r=screen(fixture,job['nodes'],job['arms'])
                            save('records.jsonl',dict(fixture=fixture,screen=r,split='development',mode=job['mode']))
                            save('events.jsonl',dict(event='screen_finished',id=fixture['id'],status=r['status']))
                    action=rng.choice(s.actions(node));index+=1
                else:
                    action=s._partner_action(node,world)
                    node.worlds=tuple(w for w in node.worlds if s._partner_action(node,w)==action)
                    if world not in node.worlds:raise ValueError('Actual world lost during replay')
                history.append(action.to_dict());node=s._apply(node,action)
            save('events.jsonl',dict(event='path_terminal',path=path,ego_decisions=index,actions=len(history),terminal_utility=s.utility(node)))
        except (RuntimeError,ValueError) as exc:save('events.jsonl',dict(event='path_unavailable',path=path,reason=str(exc)))


def select(records,limit=8):
    groups={}
    for r in records:
        if r['screen']['status']=='unavailable':continue
        key=structure_id(r['fixture'])
        group=groups.setdefault(key,dict(source=key,records=[],features=set()))
        group['records'].append(r)
        f=r['fixture'];game=f['game']
        group['features'].update(r['screen']['categories'])
        group['features'].update([f"players_{game['n_players']}",f"commitments_{game['n_actions_per_player'][0]}",f"goals_{len(game['goals'])}",r['mode']])
    chosen=[];covered=set()
    while groups and len(chosen)<limit:
        key=max(sorted(groups),key=lambda k:(len(groups[k]['features']-covered),sum(r['screen']['status']=='verified' for r in groups[k]['records'])))
        item=groups.pop(key);new=item['features']-covered
        if not new:break
        item['features']=sorted(item['features']);item['new_coverage']=sorted(new);chosen.append(item);covered.update(new)
    return chosen


def batch(args):
    out=args.output_dir
    if out.exists():raise ValueError('Use a new output directory')
    out.mkdir(parents=True);start=time.monotonic();jobs=[];records=[]
    # Balanced order visits every complexity stratum before a second seed.
    layouts=[(3,1,4),(4,1,6),(3,2,6),(4,2,8)]
    for rep in range(args.seeds_per_layout):
        for mode in ['single','multi_goal','multi_partner']:
            for index,(n,k,g) in enumerate(layouts):
                if time.monotonic()-start>=args.seconds:break
                job=dict(seed=args.seed+index*1000+rep,n=n,k=k,g=g,mode=mode,paths=args.paths,
                         nodes=args.max_nodes,remaining=args.remaining_turns,arms=args.max_arms)
                d=out/f'job-{len(jobs):03d}';d.mkdir();(d/'job.json').write_text(json.dumps(job))
                limit=min(args.job_seconds,args.seconds-(time.monotonic()-start))
                try:
                    with (d/'worker.log').open('w') as log:
                        result=subprocess.run([sys.executable,'-m','training.b_sft.coverage_batch','--worker',str(d)],stdout=log,stderr=log,timeout=max(.01,limit))
                    status='complete' if result.returncode==0 else 'worker_error'
                except subprocess.TimeoutExpired:status='timeout'
                rs=read_complete(d/'records.jsonl')
                records.extend(rs);jobs.append(dict(job=job,directory=str(d),status=status,completed_records=len(rs)))
                (out/'jobs.json').write_text(json.dumps(jobs,indent=2)+'\n')
                print(json.dumps(dict(job=len(jobs),layout=[n,k,g],mode=mode,status=status,records=len(rs))),flush=True)
            if time.monotonic()-start>=args.seconds:break
        if time.monotonic()-start>=args.seconds:break
    # Same state reached by different paths is one decision, not independent evidence.
    unique={}
    for r in records:
        f=r['fixture'];key=digest(dict(source=structure_id(f),ego=f['ego'],types=f['type_catalogues'],history=f['history']))
        unique.setdefault(key,r)
    records=list(unique.values());chosen=select(records,args.review_limit)
    (out/'records.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in records))
    (out/'review_selection.json').write_text(json.dumps(chosen,indent=2)+'\n')
    all_events=[e for j in jobs for e in read_complete(Path(j['directory'])/'events.jsonl')]
    summary=dict(path_events=dict(Counter(e['event'] for e in all_events)),jobs=len(jobs),job_status=dict(Counter(j['status'] for j in jobs)),seconds=round(time.monotonic()-start,2),
                 structures_with_records=len({structure_id(r['fixture']) for r in records}),decisions=len(records),
                 statuses=dict(Counter(r['screen']['status'] for r in records)),
                 coverage=dict(Counter(c for r in records if r['screen']['status']!='unavailable' for c in r['screen']['categories'])),
                 by_mode={mode:dict(decisions=sum(r['mode']==mode for r in records),verified=sum(r['mode']==mode and r['screen']['status']=='verified' for r in records)) for mode in ['single','multi_goal','multi_partner']},
                 selected_structures=len(chosen),training_ready=False,
                 missing=['Own-goal counterfactual certificate','Positive net information value certificate','Matched-state necessary action switch not checked by this screen'],
                 limits=['Search-window and sampled-arm limits remain; non-hit is not absence.',
                         'Worker timeout is incomplete computation, not negative evidence.',
                         'Reference partner policies and binary goals only; no LM training.',
                         'Every result is development; selection balances coverage, not a proof of sufficiency.'])
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    lines=['# 随机社会判断覆盖批次','', '仅供开发审查；不改原训练/测试数据。','', '```json',json.dumps(summary,ensure_ascii=False,indent=2),'```','',
           '## 建议审查的游戏','', '| source | 新增覆盖 | 完整记录数 |','|---|---|---:|']
    for c in chosen:lines.append(f"| {c['source']} | {', '.join(c['new_coverage'])} | {len(c['records'])} |")
    lines += ['','完整规则、历史、判断和采样分支见 [审查选择](review_selection.json)，所有结果见 [records.jsonl](records.jsonl)，预算状态见 [jobs.json](jobs.json)。']
    lines += ['', '[逐局可读审查](REVIEW.md)']
    (out/'REPORT.md').write_text('\n'.join(lines)+'\n')
    write_review(out,chosen)


def merge_batches(paths,out,limit=8):
    if out.exists():raise ValueError('Use a new output directory')
    out.mkdir(parents=True);unique={};excluded=[]
    for path in paths:
        source=path/'records.jsonl' if (path/'records.jsonl').exists() else path/'retained.jsonl'
        for r in read_complete(source):
            if r['split']!='development':raise ValueError('Do not select held-out data as development')
            f=r['fixture'];r=dict(r,origin=str(path))
            try:validate_catalogues(f)
            except ValueError as exc:
                excluded.append(dict(id=f['id'],origin=str(path),reason=str(exc)));continue
            if 'mode' not in r:
                qs=queries_for({int(p):rs for p,rs in f['type_catalogues'].items()},f['ego'])
                r['mode']='multi_partner' if len({q['player'] for q in qs})>1 else 'multi_goal' if len(qs)>1 else 'single'
            key=digest(dict(source=structure_id(f),ego=f['ego'],types=f['type_catalogues'],history=f['history']))
            unique.setdefault(key,r)
    records=list(unique.values());chosen=select(records,limit)
    (out/'records.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in records))
    (out/'review_selection.json').write_text(json.dumps(chosen,indent=2)+'\n')
    (out/'selected_fixtures.json').write_text(json.dumps(dict(fixtures=[r['fixture'] for c in chosen for r in c['records']],split='development'),indent=2)+'\n')
    (out/'exclusions.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in excluded))
    summary=dict(excluded_records=len(excluded),origins=list(map(str,paths)),exact_structures=len({structure_id(r['fixture']) for r in records}),decisions=len(records),
                 verified=sum(r['screen']['status']=='verified' for r in records),selected_structures=len(chosen),
                 coverage=dict(Counter(c for r in records if r['screen']['status']!='unavailable' for c in r['screen']['categories'])),
                 selected_features=sorted({x for c in chosen for x in c['features']}),training_ready=False,
                 limits=['Not isomorphism-deduplicated; structural counts are exact hashes.',
                         'Development-only review selection, not causal certification or completed training data.',
                         'Still missing own-goal counterfactual and positive net information value certificates.'])
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    write_review(out,chosen)
    (out/'REPORT.md').write_text('# 社会判断审查包\n\n先看 [逐局审查](REVIEW.md)，再看 [完整覆盖与来源](summary.json)。\n\n'
        +f"{summary['exact_structures']} 个精确结构、{len(records)} 个节点中，选择 {len(chosen)} 个互补结构供人工审查；未凑满数量上限。\n\n"
        +'所选结构全部节点与原始游戏参数见 [review_selection.json](review_selection.json)，可重放 fixture 见 [selected_fixtures.json](selected_fixtures.json)。\n')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--worker',type=Path)
    p.add_argument('--merge-batch',type=Path,nargs='*',default=[]);p.add_argument('--output-dir',type=Path);p.add_argument('--seed',type=int,default=98000)
    p.add_argument('--seeds-per-layout',type=int,default=1);p.add_argument('--paths',type=int,default=2)
    p.add_argument('--max-nodes',type=int,default=1000);p.add_argument('--max-arms',type=int,default=8)
    p.add_argument('--remaining-turns',type=int,default=4);p.add_argument('--review-limit',type=int,default=8)
    p.add_argument('--seconds',type=float,default=150);p.add_argument('--job-seconds',type=float,default=12)
    args=p.parse_args()
    if args.worker:worker(json.loads((args.worker/'job.json').read_text()),args.worker);return
    if args.output_dir is None:p.error('output-dir required')
    if not all(math.isfinite(x) for x in [args.seconds,args.job_seconds]) or min(args.seeds_per_layout,args.paths,args.max_nodes,args.max_arms,args.remaining_turns,args.review_limit,args.seconds,args.job_seconds)<=0:p.error('Positive budgets required')
    if args.merge_batch:merge_batches(args.merge_batch,args.output_dir,args.review_limit)
    else:batch(args)


if __name__=='__main__':main()
