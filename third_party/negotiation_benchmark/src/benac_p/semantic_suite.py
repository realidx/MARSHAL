"""One-command semantic B / P / B→P / P→B diagnostics with rational partners."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import time
import numpy as np
from benac_p.semantic_game import SemanticGame, PREFERENCES, VERSION as GAME_VERSION
from benac_p.diagnose_protocol import generate, system_prompt, submission_tool, protocol_summary, PROTOCOL_VERSION
from benac_p.diagnose_suite import dump, digest, cluster_summary

VERSION='semantic-interaction-loop-v1'
SYSTEM='''You control P0 in a three-player BENAC negotiation. Follow the public stage protocol and the stated deterministic rational partner rules. Commitments are binding. Partners have their own persistent preferences. Infer only what the evidence supports: retain every still-possible preference and exclude those ruled out. A remaining uncertainty can be a correct answer. Use the stated joint configurations to understand the implications for P2. For a supplied-judgment planning task, treat that judgment as your current information; do not invent additional evidence. Choose the action with the best terminal outcome under the publicly stated equal-frequency configurations. You are not asked to output probabilities, utility numbers, Q values, rankings or a plan variable. Return only the requested JSON object.'''
CONDITIONS=('unknown_relevant','known','unknown_irrelevant')


class Suite:
    def __init__(self,n_games=12,seed=20000):
        if n_games<2 or n_games%2:raise ValueError('n-games is an even number of matched bundles, at least 2.')
        self.n_games,self.seed=n_games,seed
        self.games={};self.tasks=[];self.labels={};self.cases={};self.arms={};self.certificates={}

    def _add_task(self,tid,kind,payload,label,parent=None):
        self.tasks.append(dict(id=tid,kind=kind,input=payload,parent=parent))
        self.labels[tid]=label

    def add_case(self,gid,cid,state,support,history,weight=1.):
        if cid in self.cases:return
        entry=self.games[gid];game=entry['game'];q=game.q_values(state,support)
        self.cases[cid]=dict(game=gid,state=state,support=support,moves=tuple(m for m,v in q),q=tuple(v for m,v in q),weight=weight)
        label=dict(game=gid,bundle=entry['bundle'],split=entry['split'],condition=game.condition,case=cid,weight=weight,
                   possible_preferences=list(support),q=[v for m,v in q],optimal_indices=[i for i,(m,v) in enumerate(q) if max(x[1] for x in q)-v<1e-9])
        belief=dict(game=game.description(),initially_possible_preferences=list(game.support),history=history,
                    question='What can currently be concluded about P1\'s preference for the first assessment? Return all and only the still-possible values: want, neutral, avoid. Do not collapse an unresolved set into a guess.')
        self._add_task(cid+'/belief','semantic_belief',belief,dict(label))
        state_text=('No preliminary commitment has been made. Choose the stage-1 interaction.' if state.turn_index==0 else
                    'Stage 1 is complete. No route is bound yet. Earlier commitments are irreversible, but contribute the same fixed past outcome to every remaining route. They neither enable nor disable any listed route. Choose the stage-2 binding route proposal. After P1 responds, the bound route will automatically be submitted to P2; you cannot switch routes then.')
        if state.turn_index==1:
            bound=[r for r in range(3) if state.commitments[0,1+r]]
            if bound:
                state_text=f'The {game.names[bound[0]]} route is already irreversibly bound. It cannot be changed; only the listed permit proposal is available. After the permit response, P2 will automatically receive the approval request for this bound route.'
        planning=dict(game=game.description(),stage=state.turn_index+1,state=state_text,
                      legal_actions=[dict(action_index=i,proposal=m.text) for i,(m,v) in enumerate(q)],
                      partner_judgment=game.judgment(support),
                      instruction='Use the supplied partner judgment to select the best listed interaction action, considering partner responses, future evidence when relevant, and the final outcome.')
        self._add_task(cid+'/plan_oracle','planning',planning,dict(label))
        model=deepcopy(planning);model.pop('partner_judgment')
        self._add_task(cid+'/plan_model','planning',model,dict(label),cid+'/belief')

    def add_arm(self,gid,arm,move):
        game=self.games[gid]['game'];branches=[]
        for branch in game.branches(game.initial(),game.support,move):
            cid=f"{gid}/after_{move.key}/{branch['response'] or 'PASS'}"
            history=[game.observed_event(move,branch['response'])]
            self.add_case(gid,cid,branch['state'],branch['support'],history,branch['weight'])
            branches.append(dict(case=cid,weight=branch['weight'],supported_preferences=list(branch['support']),response=branch['response']))
        self.arms.setdefault(gid,{})[arm]=dict(action=move.key,branches=branches)

    def build(self):
        for i in range(self.n_games):
            seed=self.seed+i;bundle=f'b{seed}';split='discovery' if i<self.n_games//2 else 'confirmation'
            for condition in CONDITIONS:
                game=SemanticGame(seed,condition);gid=f'{bundle}/{condition}'
                self.games[gid]=dict(game=game,bundle=bundle,split=split)
                cert=game.certify()
                # Certify every root evidence channel, not only the selected one.
                cert['channels']={m.key:[dict(response=b['response'],weight=b['weight'],supported_preferences=list(b['support'])) for b in game.branches(game.initial(),game.support,m)] for m in game.moves(game.initial())}
                self.certificates[gid]=cert
                self.add_case(gid,gid+'/root',game.initial(),game.support,[])
                self.add_arm(gid,'oracle',game.optimal(game.initial(),game.support)[0])
            print(f'Certified {bundle}: all three conditions',flush=True)
        return self

    def add_model_arms(self,records):
        for gid in self.games:
            root=self.cases[gid+'/root']
            for arm,suffix in (('model','plan_oracle'),('end_to_end','plan_model')):
                record=records.get(gid+'/root/'+suffix,{})
                if record.get('status')=='ok':self.add_arm(gid,arm,root['moves'][record['answer']['action_index']])

    def payload(self,task,records):
        payload=deepcopy(task['input'])
        if task['parent']:
            parent=records.get(task['parent'],{})
            if parent.get('status')!='ok':raise ValueError('Invalid or missing semantic judgment')
            game=self.games[self.labels[task['id']]['game']]['game']
            payload['partner_judgment']=game.judgment(parent['answer']['possible_preferences'])
        return payload

    def validate(self,task,answer):
        if task['kind']=='semantic_belief':
            values=answer['possible_preferences']
            if not isinstance(values,list) or not values or any(v not in PREFERENCES for v in values) or len(set(values))!=len(values):raise ValueError('Expected a nonempty unique list of want/neutral/avoid.')
            return dict(possible_preferences=[p for p in PREFERENCES if p in values])
        idx=answer['action_index']
        if isinstance(idx,bool) or not isinstance(idx,int) or not 0<=idx<len(task['input']['legal_actions']):raise ValueError('Invalid action index')
        return dict(action_index=idx)

    def oracle_answer(self,task,records):
        label=self.labels[task['id']]
        if task['kind']=='semantic_belief':return dict(possible_preferences=label['possible_preferences'])
        ctx=self.cases[label['case']];game=self.games[label['game']]['game']
        support=self.payload(task,records)['partner_judgment']['possible_preferences']
        chosen=game.optimal(ctx['state'],support)[0]
        return dict(action_index=ctx['moves'].index(chosen))


def infer_tasks(suite,records,client,out,workers,protocol,oracle_check=False):
    for task in suite.tasks:
        record=records.get(task['id'],{})
        if record.get('status')=='ok' and not oracle_check:
            if record.get('payload_hash')!=digest(suite.payload(task,records)):
                raise ValueError('Cached request payload differs; use a fresh output directory.')
    pending=[t for t in suite.tasks if t['id'] not in records or records[t['id']].get('status')=='transport_error']
    def request(task,payload):
        start=time.monotonic()
        try:
            result=generate(client,task,payload,SYSTEM,protocol)
        except Exception as exc:
            return dict(status='transport_error',error=type(exc).__name__,seconds=time.monotonic()-start)
        if result['status']=='ok':
            try:result['answer']=suite.validate(task,result['answer'])
            except (ValueError,TypeError,KeyError) as exc:result.update(status='invalid',error=str(exc))
        result['seconds']=time.monotonic()-start
        return result
    with ThreadPoolExecutor(max_workers=workers) as pool:
        while pending:
            ready=[t for t in pending if not t['parent'] or t['parent'] in records][:workers]
            if not ready:raise RuntimeError('Unresolved task dependency')
            futures={}
            for task in ready:
                pending.remove(task)
                try:payload=suite.payload(task,records)
                except ValueError as exc:
                    records[task['id']]=dict(status='blocked_parent',error=str(exc));continue
                if oracle_check:
                    records[task['id']]=dict(status='ok',answer=suite.oracle_answer(task,records),source='synthetic_oracle_check')
                else:futures[pool.submit(request,task,payload)]=(task,digest(payload))
            for future in as_completed(futures):
                task,payload_hash=futures[future];records[task['id']]=dict(future.result(),payload_hash=payload_hash)
                dump(out/'answers.json',records)
            dump(out/'answers.json',records)
            print(f'{len(records)}/{len(suite.tasks)} answers',flush=True)
            if any(records[t['id']].get('status')=='transport_error' for t in ready):
                raise RuntimeError('Transport failure saved; use --resume after resolving the service issue.')


def score(suite,records):
    rows=[];factorial=[]
    for cid,ctx in suite.cases.items():
        entry=suite.games[ctx['game']];game=entry['game']
        row=dict(case=cid,game=ctx['game'],bundle=entry['bundle'],split=entry['split'],condition=game.condition,weight=ctx['weight'])
        row['supported_preferences']=list(ctx['support'])
        row['evidence_requires_update']=set(ctx['support'])!=set(game.support)
        answers={suffix:records.get(cid+'/'+suffix,{}) for suffix in ('belief','plan_oracle','plan_model')}
        b=answers['belief'];truth=set(ctx['support']);best=max(ctx['q'])
        row['status']={k:v.get('status','missing') for k,v in answers.items()}
        if b.get('status')=='ok':
            predicted=set(b['answer']['possible_preferences'])
            row['predicted_preferences']=[p for p in PREFERENCES if p in predicted]
            row.update(belief_exact=int(predicted==truth),false_exclusions=len(truth-predicted)/len(truth),
                       unsupported_possibilities=len(predicted-truth)/max(1,3-len(truth)),
                       uncertainty_correct=int((len(predicted)>1)==(len(truth)>1)),
                       prior_only_exact=int(set(game.support)==truth))
            action=game.optimal(ctx['state'],tuple(predicted))[0]
            row['belief_decision_cost']=best-ctx['q'][ctx['moves'].index(action)]
        for suffix,key in (('plan_oracle','OL'),('plan_model','LL')):
            if answers[suffix].get('status')=='ok':row[key]=best-ctx['q'][answers[suffix]['answer']['action_index']]
        if all(a.get('status')=='ok' for a in answers.values()):
            row.update(OO=0.,LO=row['belief_decision_cost'],belief_repair=row['LL']-row['OL'])
            factorial.append(dict(row))
        else:
            factorial.append({k:row[k] for k in ('case','game','bundle','split','condition','weight')})
        rows.append(row)
    by_case={r['case']:r for r in rows};active=[];rollouts=[]
    for gid,entry in suite.games.items():
        game=entry['game'];root=game.initial();root_q={m.key:v for m,v in game.q_values(root,game.support)}
        item=dict(game=gid,bundle=entry['bundle'],split=entry['split'],condition=game.condition,arms={})
        for arm,info in suite.arms[gid].items():
            branches=info['branches'];br=[by_case[b['case']] for b in branches]
            info_score=dict(action=info['action'],reference_utility=root_q[info['action']],
                            remaining_possibilities=sum(b['weight']*len(b['supported_preferences']) for b in branches),
                            oracle_entropy=sum(b['weight']*math.log2(len(b['supported_preferences'])) for b in branches),
                            branches=[dict(b,model_status=r['status']) for b,r in zip(branches,br)])
            info_score['information_gain']=math.log2(len(game.support))-info_score['oracle_entropy']
            for metric in ('belief_exact','false_exclusions','unsupported_possibilities','belief_decision_cost','LL','uncertainty_correct'):
                if all(metric in r for r in br):info_score[metric]=sum(b['weight']*r[metric] for b,r in zip(branches,br))
            if 'belief_decision_cost' in info_score:info_score['model_updater_reference_planner_utility']=info_score['reference_utility']-info_score['belief_decision_cost']
            if 'LL' in info_score:info_score['model_updater_model_planner_utility']=info_score['reference_utility']-info_score['LL']
            item['arms'][arm]=info_score
        matrix={}
        for arm,prefix in (('oracle','O'),('model','L')):
            if arm in item['arms']:
                a=item['arms'][arm];matrix[prefix+'O']=a['reference_utility']
                if 'model_updater_reference_planner_utility' in a:matrix[prefix+'L']=a['model_updater_reference_planner_utility']
        item['J']=matrix
        if all(k in matrix for k in ('OO','OL','LO','LL')):
            item.update(chooser_repair=matrix['OL']-matrix['LL'],updater_repair_model_action=matrix['LO']-matrix['LL'],
                        updater_repair_oracle_action=matrix['OO']-matrix['OL'])
        if 'model' in item['arms']:
            item['channel_information_repair']=item['arms']['oracle']['information_gain']-item['arms']['model']['information_gain']
        if 'end_to_end' in item['arms'] and 'model_updater_model_planner_utility' in item['arms']['end_to_end']:
            item['end_to_end_utility']=item['arms']['end_to_end']['model_updater_model_planner_utility']
            item['end_to_end_regret']=max(root_q.values())-item['end_to_end_utility']
            info=suite.arms[gid]['end_to_end']
            first=next(m for m in game.moves(root) if m.key==info['action'])
            for pref in game.support:
                response,state=game.execute(root,first,pref)
                branch=next(b for b in info['branches'] if pref in b['supported_preferences'])
                rec=records[branch['case']+'/plan_model'];ctx=suite.cases[branch['case']]
                route=ctx['moves'][rec['answer']['action_index']]
                permit_response,state=game.execute(state,route,pref)
                approval=game.moves(state)[0];approval_response,state=game.execute(state,approval,pref)
                rollouts.append(dict(game=gid,hidden_configuration=pref,weight=1/len(game.support),
                    history=[game.observed_event(first,response),game.observed_event(route,permit_response),game.observed_event(approval,approval_response)],
                    terminal_commitments=state.snapshot_commitments(),terminal_utilities=[game._utility(state,p,game.rows[pref][p]) for p in range(3)],
                    initial_judgment=records[gid+'/root/belief']['answer'],updated_judgment=records[branch['case']+'/belief']['answer']))
        active.append(item)
    return dict(cases=rows,factorial=factorial,active=active,rollouts=rollouts)


def summarize(suite,scored):
    result={}
    for split in ('discovery','confirmation'):
        result[split]={}
        for condition in CONDITIONS:
            gids={gid for gid,e in suite.games.items() if e['split']==split and e['game'].condition==condition}
            cases=[r for r in scored['cases'] if r['game'] in gids]
            optimal_cases={b['case'] for gid in gids for b in suite.arms[gid]['oracle']['branches']}
            post=[r for r in cases if r['case'] in optimal_cases]
            roots=[r for r in cases if r['case'].endswith('/root')]
            active=[r for r in scored['active'] if r['game'] in gids]
            metrics={key:cluster_summary(post,key) for key in ('belief_exact','false_exclusions','unsupported_possibilities','uncertainty_correct','prior_only_exact','belief_decision_cost','OL','belief_repair')}
            metrics['initial_belief_exact']=cluster_summary(roots,'belief_exact')
            statuses=[status for r in cases for status in r['status'].values()]
            metrics['measurement']=dict(requested=len(statuses),format_valid=statuses.count('ok'),
                complete_games=sum(all(status=='ok' for r in cases if r['game']==gid for status in r['status'].values()) for gid in gids),
                expected_games=len(gids))
            metrics['root_planning_regret']=cluster_summary(roots,'OL')
            metrics['R']={k:cluster_summary([r for r in scored['factorial'] if r['case'] in optimal_cases],k) for k in ('OO','OL','LO','LL')}
            metrics['J']={k:cluster_summary([dict(game=r['game'],**({k:r['J'][k]} if k in r['J'] else {})) for r in active],k) for k in ('OO','OL','LO','LL')}
            for key in ('chooser_repair','updater_repair_model_action','updater_repair_oracle_action','channel_information_repair','end_to_end_utility','end_to_end_regret'):
                metrics[key]=cluster_summary(active,key)
            result[split][condition]=metrics
        matched=[]
        for bundle in sorted({e['bundle'] for e in suite.games.values() if e['split']==split}):
            roots=[r for r in scored['cases'] if r['bundle']==bundle and r['case'].endswith('/root')]
            row=dict(game=bundle)
            if len(roots)==3 and all('OL' in r for r in roots):
                row['all_three_conditions_optimal']=int(all(r['OL']<1e-9 for r in roots))
            matched.append(row)
        result[split]['matched_control']=cluster_summary(matched,'all_three_conditions_optimal')
    return result


def write_report(summary,mode,path):
    lines=['# Semantic BENAC-P diagnosis','',f'Run mode: {mode}.',
           'Selected, certified three-stage protocol family. No claim about unrestricted random games or cross-environment transfer.',
           'Partner responses are deterministic and terminal-rational under the public protocol; hidden configurations are enumerated, never sampled during evaluation.',
           'Confidence intervals bootstrap independent matched bundles within each condition. Conditions are not counted as independent replicates.',
           'R: regret, first letter judgment and second planner. J: utility, first letter initial chooser and second updater; continuation planner is reference.',
           'A chooser utility gain is not by itself evidence of information mediation. Inspect channel and judgment metrics together.','']
    for split,conditions in summary.items():
        for condition,s in conditions.items():
            if condition=='matched_control':
                lines.extend(['',f"All three control conditions optimal in the same bundle: {s['mean']} (95% CI {s['ci95']}; n={s['n_games']}).",''])
                continue
            lines.extend([f'## {split}: {condition}','', '| Metric | Mean | 95% CI | Complete bundles |','|---|---:|---|---:|'])
            for key in ('belief_exact','false_exclusions','unsupported_possibilities','prior_only_exact','OL','belief_repair','root_planning_regret','chooser_repair','updater_repair_model_action','updater_repair_oracle_action','channel_information_repair','end_to_end_regret'):
                x=s[key];lines.append(f"| {key} | {x['mean']} | {x['ci95']} | {x['n_games']} |")
            for name in ('R','J'):
                lines.extend(['',f'{name} table:','', '| | Reference | Model |','|---|---:|---:|',
                              f"| Reference | {s[name]['OO']['mean']} | {s[name]['OL']['mean']} |",
                              f"| Model | {s[name]['LO']['mean']} | {s[name]['LL']['mean']} |",''])
            lines.append(f"Measurement coverage: {s['measurement']}")
    Path(path).write_text('\n'.join(lines)+'\n')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--n-games',type=int,default=12,help='Even number of matched bundles; each contains all three conditions.')
    parser.add_argument('--seed',type=int,default=20000)
    parser.add_argument('--base-url',default='http://localhost:8000/v1');parser.add_argument('--model',default='Qwen/Qwen3-4B-Instruct-2507')
    parser.add_argument('--workers',type=int,default=4);parser.add_argument('--max-tokens',type=int,default=1024);parser.add_argument('--temperature',type=float,default=0.)
    parser.add_argument('--response-protocol',choices=('reasoning_tools','json_action'),default='reasoning_tools')
    parser.add_argument('--export-only',action='store_true');parser.add_argument('--oracle-check',action='store_true');parser.add_argument('--resume',action='store_true');parser.add_argument('--score-only',action='store_true')
    args=parser.parse_args(argv)
    if args.n_games<2 or args.n_games%2:parser.error('n-games must be even and at least 2.')
    if args.workers<1 or args.max_tokens<1:parser.error('workers and max-tokens must be positive.')
    if args.export_only and (args.oracle_check or args.score_only):parser.error('export-only cannot be combined with oracle-check/score-only.')
    out=args.output_dir;out.mkdir(parents=True,exist_ok=True)
    suite=Suite(args.n_games,args.seed).build();static_count=len(suite.tasks)
    manifest=dict(version=VERSION,game_version=GAME_VERSION,protocol_version=PROTOCOL_VERSION,response_protocol=args.response_protocol,
                  bundles=args.n_games,games=len(suite.games),seed=args.seed,static_tasks=static_count,
                  max_additional_tasks=6*sum(len(e['game'].support) for e in suite.games.values()),task_hash=digest(suite.tasks),system_hash=digest(system_prompt(SYSTEM,args.response_protocol)),
                  tool_hash=digest([submission_tool(t) for t in suite.tasks]),max_tokens=args.max_tokens,temperature=args.temperature,
                  model=args.model,base_url=args.base_url,oracle_check=args.oracle_check)
    if (out/'manifest.json').exists():
        old=json.loads((out/'manifest.json').read_text())
        if old!=manifest:parser.error('Manifest differs; use a fresh output directory. Never mix old or changed protocols.')
        if (out/'answers.json').exists() and not (args.resume or args.score_only):parser.error('Existing answers require --resume or --score-only.')
    elif args.resume or args.score_only:parser.error('No existing manifest to resume/score.')
    dump(out/'manifest.json',manifest)
    dump(out/'tasks.json',dict(system=system_prompt(SYSTEM,args.response_protocol),tasks=suite.tasks,tools_by_task={t['id']:submission_tool(t) for t in suite.tasks}))
    dump(out/'oracle_labels.json',suite.labels);dump(out/'certificates.json',suite.certificates)
    if args.export_only:return
    if args.score_only and not (out/'answers.json').exists():parser.error('Missing answers.json')
    records=json.loads((out/'answers.json').read_text()) if (out/'answers.json').exists() else {}
    client=None
    if not (args.oracle_check or args.score_only):
        from methods.vllm_client import OpenAICompatibleNegotiationClient
        client=OpenAICompatibleNegotiationClient(args.base_url,args.model,api_key=os.environ.get('BENAC_P_VLLM_API_KEY','EMPTY'),max_tokens=args.max_tokens,temperature=args.temperature)
    if not args.score_only:infer_tasks(suite,records,client,out,args.workers,args.response_protocol,args.oracle_check)
    suite.add_model_arms(records)
    dump(out/'dynamic_tasks.json',suite.tasks[static_count:]);dump(out/'dynamic_tools.json',{t['id']:submission_tool(t) for t in suite.tasks[static_count:]})
    dump(out/'oracle_labels.json',suite.labels);dump(out/'interventions.json',suite.arms)
    if not args.score_only:infer_tasks(suite,records,client,out,args.workers,args.response_protocol,args.oracle_check)
    scored=score(suite,records);summary=summarize(suite,scored)
    dump(out/'scores.json',scored);dump(out/'summary.json',summary);dump(out/'rollouts.json',scored['rollouts'])
    dump(out/'protocol_summary.json',protocol_summary(records))
    mode='SYNTHETIC ORACLE CHECK — not LLM results' if args.oracle_check else 'LLM'
    write_report(summary,mode,out/'report.md')
    print(f'Completed {mode}: {len(records)} tasks; {out / "report.md"}',flush=True)


if __name__=='__main__':main()
