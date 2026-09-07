"""Four paired diagnostics on native, replayable BENAC-P positions.

Fixture generation is separate from measurement. A fixture contains an original
GameSpec, independent public type catalogues and a legal full-action prefix.
No reference action is inferred from a hand-written semantic action name.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
import json
import math
import os
from itertools import product, combinations
from pathlib import Path

import numpy as np
from benac_p.endgame import Endgame, Node, Branch, SearchLimit, fingerprint
from benac_p.endgame_partner import RationalPartner, InformationStateRequired, InconsistentPartnerHistory, transcript_actions
from benac_p.schema import GameSpec, Goal, ActionRef, ResponseAction, OfferProposal, PassProposal, MenuOffer
from benac_p.runner import _normalise_proposal
from benac_p.diagnose_suite import dump, digest, cluster_summary
from benac_p.diagnose_protocol import generate, protocol_summary, submission_tool, system_prompt, PROTOCOL_VERSION, REASONING_PROFILE_VERSION

VERSION = 'native-endgame-diagnose-v4-history'
PREFERENCES = ('want','neutral','avoid')
SYSTEM = '''You control the stated ego player in a BENAC-P endgame. Use only the public rules, your preferences and supplied information. Offers and accepted menu options bind the proposed commitments immediately and irreversibly. Every player retains its original proposal turns and may actively propose. Briefly reason about the requested partner judgment or native action, then submit the requested tool call. Do not output probabilities, utility numbers, Q values or a plan variable. All remaining legal actions are listed. The reference partner specification describes its information and optimization objective; do not assume it sees others' hidden preferences.'''


def decode_action(raw):
    return ResponseAction(raw['response']) if 'response' in raw else _normalise_proposal(raw)


def render_action(node,action):
    if isinstance(action,ResponseAction):return action.value
    if isinstance(action,PassProposal):return 'PASS'
    proposer=node.state.current_proposer()
    def offer_text(offer):
        def additions(player,row):
            new=[f'A{i}' for i,(old,v) in enumerate(zip(node.state._row_tuple(player),row)) if v and not old]
            return '{'+', '.join(new)+'}'
        return f'P{proposer} adds '+additions(proposer,offer.proposer_action)+f'; P{offer.partner_id} adds '+additions(offer.partner_id,offer.partner_action)
    if isinstance(action.offer,MenuOffer):
        return f'MENU to P{action.offer.partner_id}: '+ '; '.join(f'[{i+1}] '+offer_text(o) for i,o in enumerate(action.offer.offers))
    return f'OFFER to P{action.offer.partner_id}: '+offer_text(action.offer)


class Fixture:
    def __init__(self, raw, max_nodes=20000):
        self.raw = raw
        self.id = raw['id']
        self.bundle = raw.get('bundle',str(raw.get('source',{}).get('seed',self.id)))
        self.split = raw.get('split',('discovery' if raw['source']['seed']%2==0 else 'confirmation') if 'seed' in raw.get('source',{}) else 'exploratory')
        self.ego = raw.get('ego',0)
        self.target_player = raw['query']['player']
        self.target_goals = tuple(raw['query'].get('goals',[raw['query'].get('goal')]))
        self.target_goal = self.target_goals[0]
        public = raw['game']
        goals = tuple(Goal(g['goal_id'], tuple(ActionRef(**a) for a in g['required_actions'])) for g in public['goals'])
        self.spec = GameSpec(public['n_players'], tuple(public['n_actions_per_player']), goals,
            np.zeros((public['n_players'],len(goals)),dtype=np.int8), tuple(public['round_robin']),
            public['max_changes'], 0, forbidden_actions=None if public.get('forbidden_actions') is None else np.array(public['forbidden_actions']), menu_enabled=public.get('menu_enabled',False))
        if self.spec.n_players<3 or not self.spec.menu_enabled:raise ValueError('Native diagnosis requires at least three players and an explicitly enabled menu mechanism.')
        self.types = {int(p):tuple(tuple(row) for row in rows) for p,rows in raw['type_catalogues'].items()}
        if set(self.types) != set(range(self.spec.n_players)):
            raise ValueError('All players require a public independent type catalogue.')
        self.own = tuple(raw['own_preferences'])
        if self.own not in self.types[self.ego]:
            raise ValueError('Ego own preferences must belong to its public catalogue.')
        if self.target_player == self.ego or self.target_player not in self.types or any(not isinstance(g,int) or not 0 <= g < len(goals) for g in self.target_goals):
            raise ValueError('Invalid partner judgment target.')
        # First measurement interface: isolate one uncertain preference. Do not
        # silently collapse multi-partner joint beliefs into marginal labels.
        for p,rows in self.types.items():
            if p != self.target_player and len(rows) != 1:
                raise ValueError('This semantic interface requires other preference rows to be settled; the search engine itself supports independent multi-player uncertainty.')
            if p == self.target_player and any(any(a!=b for j,(a,b) in enumerate(zip(rows[0],r)) if j not in self.target_goals) for r in rows):
                raise ValueError('Only queried preferences may vary in the semantic interface.')
        order={1:0,0:1,-1:2}
        profiles=sorted(self.types[self.target_player],key=lambda r:tuple(order[r[g]] for g in self.target_goals))
        dimensions=[{r[g] for r in profiles} for g in self.target_goals]
        if len(profiles)!=math.prod(len(d) for d in dimensions):raise ValueError('Queried goal preferences must have a Cartesian-product prior; no invented within-player binding.')
        labels={1:'want',0:'neutral',-1:'avoid'}
        self.profile_labels={r:(labels[r[self.target_goal]] if len(self.target_goals)==1 else ', '.join(f'G{g}={labels[r[g]]}' for g in self.target_goals)) for r in profiles}
        self.belief_options=list(self.profile_labels.values())
        self.partner = RationalPartner(self.spec,self.types,self.ego,max_nodes)
        self.search = Endgame(self.spec,self.ego,self.own,{p:r for p,r in self.types.items() if p!=self.ego},self.partner,max_nodes=max_nodes)
        self.prefix = [decode_action(a) for a in raw.get('history',[])]
        self.root = self.search.replay(self.prefix)
        if self.search.actor(self.root) != self.ego:
            raise ValueError('The frozen position must stop at a real ego decision.')
        if 'initially_possible_preferences' in raw:
            self.root = self.with_judgment(self.root,raw['initially_possible_preferences'],base=self.root.worlds)
        self.prior = self.root.worlds
        self.initial_support=raw.get('initially_possible_preferences',self.support(Node(self.root.state,self.search.worlds,self.root.pending)))
        if self.root.state.is_terminal:
            raise ValueError('A root position must have an actual remaining decision.')

    def support(self,node):
        present={w[self.target_player] for w in node.worlds}
        return [label for row,label in self.profile_labels.items() if row in present]

    def with_judgment(self,node,support,base=None):
        if not support or any(v not in self.belief_options for v in support):
            raise ValueError('A nonempty semantic possibility set is required.')
        worlds = tuple(w for w in (self.search.worlds if base is None else base)
                       if self.profile_labels[w[self.target_player]] in support)
        if not worlds:
            raise ValueError('Judgment has no type in the public catalogue.')
        return Node(node.state,worlds,node.pending)

    def window_step(self,node,action):
        """Execute one ego decision, then stop at its next native decision.

        ACCEPT/REJECT/CHOOSE count as decisions too; never fold them into a
        reference policy before the second measured ego action.
        """
        return self.search.step(node,action)

    def history_text(self,node):
        actions=transcript_actions(node.state.public_state()['transcript'])
        if node.pending is not None:actions.append(OfferProposal(node.pending))
        current=self.search.initial();text=[]
        for action in actions:
            text.append(dict(turn=current.state.turn_index,player=f'P{self.search.actor(current)}',action=render_action(current,action)))
            current=self.search._apply(current,action)
        return text

    def public(self):
        return dict(n_players=self.spec.n_players,goals={f'G{g.goal_id}':' AND '.join(f'P{a.player_id}.A{a.action_id}' for a in g.required_actions) for g in self.spec.goals},
            n_actions_per_player=list(self.spec.n_actions_per_player),max_changes=self.spec.max_changes,
            forbidden_actions=None if self.spec.forbidden_actions is None else self.spec.forbidden_actions.tolist(),
            round_robin=list(self.spec.round_robin),ego=self.ego,own_preferences={f'G{i}':{1:'want',0:'neutral',-1:'avoid'}[v] for i,v in enumerate(self.own)},
            preference_labels={'1':'want','0':'neutral','-1':'avoid'},semantic_profile_options=self.belief_options,
            type_catalogues={f'P{p}':[{f'G{i}':{1:'want',0:'neutral',-1:'avoid'}[v] for i,v in enumerate(r)} for r in rows] for p,rows in self.types.items()},
            partner=self.partner.specification(),
            rules='Goals are satisfied exactly when all their listed commitments are bound. Terminal utility adds own want goals and subtracts own avoid goals. Pass consumes a proposal turn. An offer changes only proposer/recipient commitments on acceptance; a menu binds exactly its selected option. Rejection binds nothing. No stage-specific action restrictions exist.')


class Suite:
    def __init__(self,fixtures):
        self.fixtures={f.id:f for f in fixtures}
        if len(self.fixtures)!=len(fixtures):raise ValueError('Duplicate fixture IDs.')
        self.tasks=[];self.labels={};self.cases={};self.arms={};self.certificates={}

    def add_case(self,f,node,cid,evidence=(),root_action=None):
        if cid in self.cases:return
        q=() if node.state.is_terminal else f.search.q_values(node)
        label=dict(fixture=f.id,bundle=f.bundle,split=f.split,case=cid,support=f.support(node),q=[v for _,v in q],
                   optimal_indices=[] if not q else [i for i,(_,v) in enumerate(q) if max(x[1] for x in q)-v<1e-9])
        self.cases[cid]=dict(f=f,node=node,q=q)
        belief=dict(game=f.public(),initially_possible_preferences=f.initial_support,
            history=f.history_text(node),
            query=dict(player=f.target_player,goals=list(f.target_goals)),
            question='Which listed semantic preference profiles remain possible for the queried partner and goal(s)? Use the supplied initial possibilities and public evidence. The population catalogue does not restore already excluded types. Include every supported possibility and no unsupported possibility.')
        # Root B uses the already conditioned episode information. Post B adds
        # every observed partner proposal/response, not only a selected response.
        self.tasks.append(dict(id=cid+'/belief',kind='semantic_belief',input=belief,parent=None,belief_options=f.belief_options))
        self.labels[cid+'/belief']=label
        if q:
            public_state=dict(turn=node.state.turn_index,current_proposer=node.state.current_proposer(),
                              commitments={f'P{p}':[f'A{i}' for i,v in enumerate(row) if v] for p,row in enumerate(node.state.snapshot_commitments())},
                              remaining_proposers=list(f.spec.round_robin[node.state.turn_index:]))
            planning=dict(game=f.public(),state=public_state,
                history=f.history_text(node),initially_possible_preferences=f.initial_support,
                pending_offer=None if node.pending is None else render_action(node,OfferProposal(node.pending)),
                partner_judgment=dict(player=f.target_player,goals=list(f.target_goals),possible_preferences=f.support(node)),
                legal_actions=[dict(action_index=i,action=render_action(node,a)) for i,(a,_) in enumerate(q)],
                instruction='Select the action with best expected terminal outcome using the public history, current state and supplied partner judgment. Consider partner responses, future proposal turns and evidence. The supplied judgment is an assessment of the partner; the public history remains available for your planning.')
            for suffix,parent in [('plan_oracle',None),('plan_model',cid+'/belief')]:
                self.tasks.append(dict(id=cid+'/'+suffix,kind='planning',input=deepcopy(planning),parent=parent))
                self.labels[cid+'/'+suffix]=label

    def add_arm(self,f,name,action):
        branches=[]
        action_key=digest(action.to_dict())[:12]
        for i,b in enumerate(f.window_step(f.root,action)):
            cid=f'{f.id}/after_{action_key}/{i}'
            self.add_case(f,b.node,cid,b.evidence,action.to_dict())
            branches.append(dict(case=cid,weight=b.weight,evidence=list(b.evidence),support=f.support(b.node)))
        self.arms.setdefault(f.id,{})[name]=dict(action=action.to_dict(),branches=branches)

    def build(self):
        for f in self.fixtures.values():
            self.add_case(f,f.root,f.id+'/root')
            q=self.cases[f.id+'/root']['q'];best=max(v for _,v in q)
            channels=[]
            for a,v in q:
                branches=f.window_step(f.root,a)
                entropy=sum(b.weight*math.log2(len(b.node.worlds)) for b in branches)
                frozen_value=0.;frozen_defined=True
                for branch in branches:
                    n=branch.node
                    if n.state.is_terminal:
                        frozen_value+=branch.weight*f.search.utility(n)
                    else:
                        try:
                            sq=f.search.q_values(f.with_judgment(n,f.support(f.root)))
                        except InconsistentPartnerHistory:
                            frozen_defined=False;continue
                        sv=max(x for _,x in sq)
                        ix=next(i for i,(_,x) in enumerate(sq) if sv-x<1e-9)
                        actual=f.search.q_values(n)
                        frozen_value+=branch.weight*actual[ix][1]
                channels.append(dict(action=a.to_dict(),value=v,judgment_update_gain=max(0.,v-frozen_value) if frozen_defined else None,posterior_entropy=entropy,
                    active_partner_proposal=any(e['player_id']!=f.ego and e['action'].get('action') in ('OFFER','MENU') for b in branches for e in b.evidence),
                    branches=[dict(weight=b.weight,support=f.support(b.node),terminal=b.node.state.is_terminal) for b in branches]))
            choice=next(a for a,v in q if best-v<1e-9)
            self.add_arm(f,'oracle',choice)
            low=min(range(len(q)),key=lambda i:-channels[i]['posterior_entropy'])
            self.add_arm(f,'low_information',q[low][0])
            high=min(range(len(q)),key=lambda i:channels[i]['posterior_entropy'])
            self.add_arm(f,'high_information',q[high][0])
            self.certificates[f.id]=dict(version=VERSION,bundle=f.bundle,split=f.split,legal_history=True,
                independent_catalogues=True,full_native_actions=True,active_partner_enabled=True,
                remaining_proposal_turns=len(f.spec.round_robin)-f.root.state.turn_index,
                remaining_ego_proposal_turns=f.spec.round_robin[f.root.state.turn_index:].count(f.ego),
                root_is_ego_proposal=f.root.pending is None,
                menu_actions=sum(isinstance(a,OfferProposal) and isinstance(a.offer,MenuOffer) for a,v in q),
                channels=channels,action_value_span=best-min(v for _,v in q),
                evidence_channel_span=max(c['posterior_entropy'] for c in channels)-min(c['posterior_entropy'] for c in channels),
                planning_history_included=True,
                belief_repair_intervention="Same public history, state and actions; replace only explicit partner judgment in fresh contexts. Measures judgment-assistance, not isolation of internal belief computation.",
                partner_optimality=f.partner.specification())
            cert=self.certificates[f.id]
            perfect=sum(f.search.value(Node(f.root.state,(w,),f.root.pending)) for w in f.root.worlds)/len(f.root.worlds)
            cert['perfect_information_gap']=max(0.,perfect-best)
            candidates=[]
            for cid,ctx in self.cases.items():
                if ctx['f'] is not f or not ctx['q']:continue
                value=max(v for _,v in ctx['q']);worst=0.
                probe_subsets=[(v,) for v in f.belief_options]+[tuple(f.belief_options)]
                for group in [probe_subsets]:
                    for subset in group:
                        try:
                            sq=f.search.q_values(f.with_judgment(ctx['node'],subset))
                        except InconsistentPartnerHistory:
                            continue
                        sv=max(v for _,v in sq)
                        indices=[i for i,(_,v) in enumerate(sq) if sv-v<1e-9]
                        worst=max(worst,max(value-ctx['q'][index][1] for index in indices))
                candidates.append((set(f.support(ctx['node']))!=set(f.initial_support),worst,cid))
            candidates.sort(reverse=True)
            cert['primary_case']=candidates[0][2]
            cert['belief_update_opportunity']=candidates[0][0]
            cert['belief_error_task_cost']=candidates[0][1]
            cert['belief_cost_definition']='Potential loss of an action that is optimal under a wrong semantic judgment; maximized over computable singleton and full-prior probe judgments and their optimal ties. Counterfactual types inconsistent with public history are excluded from this secondary witness. This is an opportunity witness, not measured model repair or the canonical R_LO cost.'
            type_q=[f.search.q_values(Node(f.root.state,(w,),f.root.pending)) for w in f.root.worlds]
            common_optimal=set(range(len(q)));cross_regret=0.
            for qs in type_q:
                best_type=max(v for _,v in qs)
                optimal={i for i,(_,v) in enumerate(qs) if best_type-v<1e-9}
                common_optimal &= optimal
                for qt in type_q:
                    cross_regret=max(cross_regret,max((max(v for _,v in qt)-qt[i][1] for i in optimal),default=0.))
            cert['type_specific_optimal_action_regret']=cross_regret
            cert['common_optimal_action_indices']=sorted(common_optimal)
            cert['same_action_update_gain']=max((c['judgment_update_gain'] for c in channels if c['judgment_update_gain'] is not None),default=None)
            cert['oracle_action_update_gain']=next(c['judgment_update_gain'] for c in channels if c['action']==choice.to_dict())
            cert['condition']='known' if len(f.root.worlds)==1 else ('unknown_relevant' if cross_regret>1e-9 else 'unknown_irrelevant')
            cert['active_partner_proposal']=any(c['active_partner_proposal'] for c in channels)
            cert['continuing_evidence_opportunity']=any(not b['terminal'] and len(b['support'])<len(f.support(f.root)) for c in channels for b in c['branches'])
            cert['partner_policy_proofs']=len(f.partner.labels)
            cert['window_value_preserved']=all(abs(v-sum(b.weight*f.search.value(b.node) for b in f.window_step(f.root,a)))<1e-9 for a,v in q)
            if not cert['window_value_preserved']:raise AssertionError('Native decision window changed the reference value.')
            print(f'Certified mechanics: {f.id}; {len(q)} legal root actions; {cert["condition"]}',flush=True)
        return self

    def payload(self,t,records):
        p=deepcopy(t['input'])
        if t['parent']:
            p['partner_judgment']['possible_preferences']=records[t['parent']]['answer']['possible_preferences']
        return p

    def answer(self,t,records):
        label=self.labels[t['id']]
        if t['kind']=='semantic_belief':return dict(possible_preferences=label['support'])
        c=self.cases[label['case']];node=c['f'].with_judgment(c['node'],self.payload(t,records)['partner_judgment']['possible_preferences'])
        q=c['f'].search.q_values(node);best=max(v for _,v in q)
        return dict(action_index=next(i for i,(_,v) in enumerate(q) if best-v<1e-9))

    def validate(self,t,answer):
        if t['kind']=='semantic_belief':
            values=answer.get('possible_preferences')
            if not isinstance(values,list) or not values or len(values)!=len(set(values)) or any(v not in t['belief_options'] for v in values):raise ValueError('Invalid possibility set.')
            return dict(possible_preferences=[v for v in t['belief_options'] if v in values])
        i=answer.get('action_index')
        if isinstance(i,bool) or not isinstance(i,int) or not 0<=i<len(t['input']['legal_actions']):raise ValueError('Invalid action index.')
        return dict(action_index=i)

    def model_arms(self,records):
        for f in self.fixtures.values():
            rec=records.get(f.id+'/root/plan_oracle',{})
            if rec.get('status')=='ok':
                self.add_arm(f,'model',self.cases[f.id+'/root']['q'][rec['answer']['action_index']][0])


def measure(suite,records):
    cases={};active=[]
    for cid,c in suite.cases.items():
        f,node,q=c['f'],c['node'],c['q']
        row=dict(game=f.bundle,fixture=f.id,split=f.split,case=cid,terminal=node.state.is_terminal,support=f.support(node))
        b=records.get(cid+'/belief',{})
        if b.get('status')=='ok':
            pred=set(b['answer']['possible_preferences']);truth=set(row['support'])
            row.update(belief_exact=int(pred==truth),false_exclusions=len(truth-pred)/len(truth),unsupported_possibilities=len(pred-truth)/max(1,len(f.belief_options)-len(truth)))
        if q:
            best=max(v for _,v in q)
            for suffix,key in [('plan_oracle','OL'),('plan_model','LL')]:
                r=records.get(cid+'/'+suffix,{})
                if r.get('status')=='ok':row[key]=best-q[r['answer']['action_index']][1]
            if 'OL' in row and 'LL' in row:row.update(OO=0.,belief_repair=row['LL']-row['OL'])
            if b.get('status')=='ok':
                try:
                    subjective=f.with_judgment(node,b['answer']['possible_preferences'])
                    sq=f.search.q_values(subjective);sv=max(v for _,v in sq)
                    index=next(i for i,(_,v) in enumerate(sq) if sv-v<1e-9)
                    row['LO']=best-q[index][1]
                except (ValueError,SearchLimit) as exc:
                    row['LO_unavailable']=str(exc)
        cases[cid]=row
    for fid,arms in suite.arms.items():
        f=suite.fixtures[fid];entry=dict(game=f.bundle,fixture=fid,split=f.split,arms={})
        root_values={fingerprint(a.to_dict()):v for a,v in suite.cases[fid+'/root']['q']}
        for name,arm in arms.items():
            bs=arm['branches'];value=root_values[fingerprint(arm['action'])]
            data=dict(reference_utility=value,
                oracle_entropy=sum(b['weight']*math.log2(len(suite.cases[b['case']]['node'].worlds)) for b in bs))
            for metric in ('belief_exact','false_exclusions','unsupported_possibilities'):
                if all(metric in cases[b['case']] for b in bs):data[metric]=sum(b['weight']*cases[b['case']][metric] for b in bs)
            for metric,name_out in [('LO','reference_planner_with_model_judgment'),('LL','model_second_decision_then_reference')]:
                if all(cases[b['case']]['terminal'] or metric in cases[b['case']] for b in bs):
                    data[name_out]=value-sum(b['weight']*cases[b['case']].get(metric,0.) for b in bs)
            entry['arms'][name]=data
        if 'model' in entry['arms']:
            o,m=entry['arms']['oracle'],entry['arms']['model']
            entry['channel_information_repair']=m['oracle_entropy']-o['oracle_entropy']
            if all('reference_planner_with_model_judgment' in a for a in (o,m)):
                entry['J']={'OO':o['reference_utility'],'OL':o['reference_planner_with_model_judgment'],
                            'LO':m['reference_utility'],'LL':m['reference_planner_with_model_judgment']}
                j=entry['J']
                entry.update(chooser_repair=j['OL']-j['LL'],updater_repair_model_action=j['LO']-j['LL'],updater_repair_oracle_action=j['OO']-j['OL'])
            for name,arm in [('oracle',o),('model',m)]:
                if 'belief_exact' in arm:entry[name+'_action_belief_exact']=arm['belief_exact']
        active.append(entry)
    return dict(cases=list(cases.values()),active=active)


def run_tasks(suite,records,out,args,client):
    pending=list(suite.tasks)
    def request(t,p):
        if args.oracle_check:r=dict(status='ok',answer=suite.answer(t,records),source='synthetic_oracle_check')
        else:
            try:r=generate(client,t,p,SYSTEM,'reasoning_tools','balanced',args.finalization_tokens)
            except Exception as exc:r=dict(status='transport_error',error=type(exc).__name__)
        if r['status']=='ok':
            try:r['answer']=suite.validate(t,r['answer'])
            except (ValueError,TypeError,KeyError) as exc:r.update(status='invalid',error=str(exc))
        return dict(r,payload_hash=digest(p))
    with ThreadPoolExecutor(max_workers=1 if args.oracle_check else args.workers) as pool:
        while pending:
            ready=[t for t in pending if not t['parent'] or t['parent'] in records][:args.workers]
            if not ready:raise RuntimeError('Unresolved task dependency.')
            jobs=[]
            for t in ready:
                pending.remove(t)
                if t['parent'] and records.get(t['parent'],{}).get('status')!='ok':
                    records[t['id']]=dict(status='blocked_parent');continue
                p=suite.payload(t,records);h=digest(p)
                if t['id'] in records and records[t['id']].get('status')!='transport_error':
                    if records[t['id']].get('payload_hash')!=h:raise ValueError('Resume payload changed.')
                    continue
                jobs.append((t,pool.submit(request,t,p)))
            failure=False
            for t,job in jobs:
                records[t['id']]=job.result()
                failure |= records[t['id']]['status']=='transport_error'
                dump(out/'answers.json',records)
            if jobs:print(f'{len(records)}/{len(suite.tasks)} answers',flush=True)
            if failure:raise RuntimeError('Transport failure saved. Resume after fixing service.')


def preflight(suite,client,out,args):
    base=deepcopy(next(t for t in suite.tasks if t['kind']=='semantic_belief'))
    path=out/'belief_preflight_answers.json'
    records=json.loads(path.read_text()) if path.exists() else {};checks=[]
    options=base['belief_options']
    for name,support in [(f'known_{i}',[v]) for i,v in enumerate(options[:3])]+[('unresolved',options)]:
        task=deepcopy(base);task['id']='preflight/'+name
        task['input'].update(initially_possible_preferences=support,history=[])
        h=digest(task['input']);r=records.get(task['id'])
        if r and r.get('payload_hash')!=h:raise ValueError('Preflight input changed.')
        if not r or r['status']=='transport_error':
            if args.oracle_check:r=dict(status='ok',answer=dict(possible_preferences=support),source='synthetic_oracle_check')
            else:
                try:r=generate(client,task,task['input'],SYSTEM,'reasoning_tools','balanced',args.finalization_tokens)
                except Exception as exc:r=dict(status='transport_error',error=type(exc).__name__)
            if r['status']=='ok':
                try:r['answer']=suite.validate(task,r['answer'])
                except (ValueError,KeyError,TypeError) as exc:r.update(status='invalid',error=str(exc))
            records[task['id']]=dict(r,payload_hash=h);dump(path,records)
        checks.append(r['status']=='ok' and set(r['answer']['possible_preferences'])==set(support))
    dump(out/'belief_preflight_summary.json',dict(passed=all(checks),correct=sum(checks),total=4,protocol=protocol_summary(records)))
    return all(checks)


def selection_readiness(suite,min_games=1):
    cs=list(suite.certificates.values());missing=[]
    independent={}
    for split in ('discovery','confirmation'):
        for condition in ('known','unknown_relevant','unknown_irrelevant'):
            selected=[c for c in cs if c['condition']==condition and c['split']==split and c['action_value_span']>1e-9 and c['root_is_ego_proposal'] and c['menu_actions']>0 and 1<=c['remaining_ego_proposal_turns']<=2]
            n=len({c['bundle'] for c in selected});independent[split+'/'+condition]=n
            if n<min_games:missing.append(f'{split}/{condition}: {n}/{min_games} independent games')
        split_cs=[c for c in cs if c['split']==split]
        if not any(c['belief_update_opportunity'] for c in split_cs):missing.append(split+': no evidence-based B judgment update')
        if not any(c['condition']=='unknown_relevant' and c['continuing_evidence_opportunity'] and c['active_partner_proposal'] and c['evidence_channel_span']>1e-9 for c in split_cs):missing.append(split+': no action-dependent evidence before a remaining ego decision in a type-sensitive position')
    return dict(passed=not missing,missing=missing,independent_games=independent,
        scope='Conditional diagnostic opportunities, not a guarantee of model weaknesses or positive repair effects. Common optimal menus remain valid in every condition; no action change is demanded without utility regret.')


def mine_selected(args,out):
    from benac_p.endgame_mine import candidates
    from benac_p.endgame import SearchLimit
    from types import SimpleNamespace
    config={k:getattr(args,k) for k in ('seed','candidate_seeds','actions_per_player','n_goals','rounds','unknown_goals','max_nodes','min_games_per_condition','max_remaining_turns')}
    config.update(candidate_version='native-candidates-v3',partner_version=RationalPartner.VERSION,suite_version=VERSION)
    cache=out/'selection.json';selected={};attempts=[];start=args.seed
    if cache.exists():
        saved=json.loads(cache.read_text())
        if saved['config']!=config:raise ValueError('Generator settings changed; use a fresh output directory.')
        if saved.get('complete'):return dict(fixtures=saved['fixtures'],selection_config=config)
        selected={(e['bundle'],e['condition']):e for e in saved.get('selected_entries',[])}
        attempts=saved.get('attempts',[]);start=saved.get('next_seed',start)
    for seed in range(start,args.seed+args.candidate_seeds):
        for raw in candidates(seed,args.max_nodes,args.actions_per_player,args.n_goals,args.rounds,args.unknown_goals,
                              lambda r:attempts.append(dict(r,selected=False)),args.max_remaining_turns):
            try:
                f=Fixture(raw,args.max_nodes)
                if f.root.pending is not None:
                    attempts.append(dict(id=f.id,selected=False,reason='Root selection requires an ego proposal; response decisions remain inside diagnostic branches.'))
                    continue
                probe=Suite([f]).build();cert=probe.certificates[f.id]
                key=(f.bundle,cert['condition']);slot=(f.split,cert['condition'])
                qualifies=cert['action_value_span']>1e-9 and cert['root_is_ego_proposal'] and cert['menu_actions']>0 and 1<=cert['remaining_ego_proposal_turns']<=2
                if cert['condition']=='unknown_relevant':qualifies &= cert['continuing_evidence_opportunity'] and cert['active_partner_proposal'] and cert['evidence_channel_span']>1e-9
                quality=(int(cert['belief_update_opportunity'] and cert['belief_error_task_cost']>1e-9),cert['belief_error_task_cost'],cert['evidence_channel_span'])
                kept=False
                if qualifies:
                    peers={k:e for k,e in selected.items() if (e['split'],e['condition'])==slot}
                    if key in selected:
                        if quality>tuple(selected[key]['quality']):kept=True
                    elif len(peers)<args.min_games_per_condition:kept=True
                    else:
                        worst=min(peers,key=lambda k:tuple(peers[k]['quality']))
                        if quality>tuple(peers[worst]['quality']):del selected[worst];kept=True
                    if kept:selected[key]=dict(raw=raw,certificate=cert,bundle=f.bundle,split=f.split,condition=cert['condition'],quality=list(quality))
                attempts.append(dict(id=f.id,selected=kept,condition=cert['condition'],reason=None if kept else 'no required opportunity, duplicate game/condition, or filled quota'))
            except (SearchLimit,InformationStateRequired) as exc:
                attempts.append(dict(id=raw['id'],selected=False,reason=str(exc)))
        proof=SimpleNamespace(certificates={e['raw']['id']:e['certificate'] for e in selected.values()})
        readiness=selection_readiness(proof,args.min_games_per_condition)
        fixtures=[e['raw'] for e in selected.values()]
        dump(out/'readiness.json',readiness)
        dump(cache,dict(config=config,fixtures=fixtures,selected_entries=list(selected.values()),attempts=attempts,
                        next_seed=seed+1,complete=readiness['passed']))
        print(f'Selection seed {seed}: {len(fixtures)} positions; readiness={readiness["passed"]}',flush=True)
        if readiness['passed']:break
    return dict(fixtures=[e['raw'] for e in selected.values()],selection_config=config)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--fixtures',type=Path)
    p.add_argument('--generate',action='store_true',help='Mine certified native positions; default when no fixture file is supplied.')
    p.add_argument('--seed',type=int,default=30000);p.add_argument('--candidate-seeds',type=int,default=64)
    p.add_argument('--actions-per-player',type=int,default=2);p.add_argument('--n-goals',type=int,default=8);p.add_argument('--rounds',type=int,default=2);p.add_argument('--unknown-goals',type=int,choices=(1,2),default=1)
    p.add_argument('--min-games-per-condition',type=int,default=6,help='Independent source games per condition in EACH preassigned split.')
    p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--export-only',action='store_true');p.add_argument('--oracle-check',action='store_true');p.add_argument('--resume',action='store_true');p.add_argument('--score-only',action='store_true')
    p.add_argument('--base-url',default='http://localhost:8000/v1');p.add_argument('--model',default='Qwen/Qwen3-4B-Instruct-2507')
    p.add_argument('--max-tokens',type=int,default=1024);p.add_argument('--finalization-tokens',type=int,default=128)
    p.add_argument('--max-nodes',type=int,default=20000)
    p.add_argument('--max-remaining-turns',type=int,default=3,help='Mine positions with at most this many original proposal turns remaining (1..6). No turns are removed.')
    p.add_argument('--workers',type=int,default=4)
    p.add_argument('--score-max-nodes',type=int,help='Separate exact counterfactual-scoring budget; default 4x max-nodes. May be increased with score-only.')
    p.add_argument('--belief-preflight',action=argparse.BooleanOptionalAction,default=True)
    args=p.parse_args(argv)
    if not 1<=args.max_remaining_turns<=6:p.error('max-remaining-turns must be in 1..6.')
    if args.score_max_nodes is not None and args.score_max_nodes<1:p.error('score-max-nodes must be positive.')
    if args.export_only and (args.oracle_check or args.score_only):p.error('Export cannot be combined with oracle-check/score-only.')
    if min(args.max_tokens,args.max_nodes,args.workers,args.candidate_seeds,args.min_games_per_condition,args.actions_per_player,args.n_goals,args.rounds)<1 or args.finalization_tokens<0:p.error('Invalid budget.')
    if not args.fixtures and args.n_goals>3*args.actions_per_player**2+args.actions_per_player**3:p.error('Too many distinct 2/3-player goals for this action count.')
    if args.generate and args.fixtures:p.error('Use fixtures or generate, not both.')
    out=args.output_dir;out.mkdir(parents=True,exist_ok=True)
    if args.fixtures:
        raw=json.loads(args.fixtures.read_text())
    else:
        raw=mine_selected(args,out)
    suite=Suite([Fixture(f,args.max_nodes) for f in raw['fixtures']]).build()
    if not suite.fixtures:
        dump(out/'readiness.json',selection_readiness(suite,args.min_games_per_condition))
        p.error('No qualifying positions in this fixture file or candidate budget. Inspect selection.json; no model requests were made.')
    out=args.output_dir;out.mkdir(parents=True,exist_ok=True)
    manifest=dict(version=VERSION,fixtures_hash=digest(raw),system_hash=digest(system_prompt(SYSTEM,'reasoning_tools','balanced')),
        protocol_version=PROTOCOL_VERSION,reasoning_profile_version=REASONING_PROFILE_VERSION,reasoning_profile='balanced',
        task_hash=digest(suite.tasks),label_hash=digest(suite.labels),partner_version=RationalPartner.VERSION,
        belief_preflight=args.belief_preflight,finalization_version='bounded-submission-v1',tool_hash=digest([submission_tool(t) for t in suite.tasks]),
        model=args.model,base_url=args.base_url,max_tokens=args.max_tokens,finalization_tokens=args.finalization_tokens,
        max_nodes=args.max_nodes,min_games_per_condition=args.min_games_per_condition,oracle_check=args.oracle_check)
    if (out/'manifest.json').exists():
        if json.loads((out/'manifest.json').read_text())!=manifest:p.error('Manifest changed; use a fresh output directory.')
        if (out/'answers.json').exists() and not (args.resume or args.score_only):p.error('Existing answers require --resume or --score-only.')
    elif args.resume or args.score_only:p.error('No manifest to resume/score.')
    if args.score_only and not (out/'answers.json').exists():p.error('No answers.json to score.')
    dump(out/'manifest.json',manifest);dump(out/'fixtures.json',raw)
    dump(out/'certificates.json',suite.certificates);dump(out/'tasks.json',suite.tasks);dump(out/'oracle_labels.json',suite.labels)
    dump(out/'readiness.json',selection_readiness(suite,args.min_games_per_condition))
    if args.export_only:return
    if not args.oracle_check:
        readiness=selection_readiness(suite,args.min_games_per_condition)
        dump(out/'readiness.json',readiness)
        if not readiness['passed']:p.error('Fixture selection is incomplete: '+ '; '.join(readiness['missing'])+'. No model calls were made.')
    records=json.loads((out/'answers.json').read_text()) if (out/'answers.json').exists() else {}
    client=None
    if not (args.oracle_check or args.score_only):
        from methods.vllm_client import OpenAICompatibleNegotiationClient
        client=OpenAICompatibleNegotiationClient(args.base_url,args.model,api_key=os.environ.get('BENAC_P_VLLM_API_KEY','EMPTY'),max_tokens=args.max_tokens,temperature=0.)
    if args.belief_preflight and not args.score_only and not preflight(suite,client,out,args):p.exit(2,'Belief preflight failed; no full model measurement was started. Wrong answers are retained.\n')
    if not args.score_only:run_tasks(suite,records,out,args,client)
    suite.model_arms(records)
    dump(out/'tasks.json',suite.tasks);dump(out/'oracle_labels.json',suite.labels);dump(out/'interventions.json',suite.arms)
    dump(out/'tools_by_task.json',{t['id']:submission_tool(t) for t in suite.tasks})
    if not args.score_only:run_tasks(suite,records,out,args,client)
    scoring_budget=args.score_max_nodes or 4*args.max_nodes
    for f in suite.fixtures.values():
        f.search.max_nodes=scoring_budget;f.partner.max_nodes=scoring_budget
    dump(out/'scoring_config.json',dict(max_nodes=scoring_budget))
    scored=measure(suite,records);dump(out/'scores.json',scored);dump(out/'protocol_summary.json',protocol_summary(records))
    summary=dict(mode='synthetic oracle check' if args.oracle_check else 'LLM',conditions={})
    for split,condition in product(('discovery','confirmation','exploratory'),('known','unknown_relevant','unknown_irrelevant')):
        ids={c['primary_case'] for c in suite.certificates.values() if c['condition']==condition and c['split']==split}
        rows=[r for r in scored['cases'] if r['case'] in ids]
        active=[r for r in scored['active'] if suite.certificates[r['fixture']]['condition']==condition and r['split']==split]
        if not rows and not active:continue
        summary['conditions'][split+'/'+condition]=dict(
            root_planning_regret=cluster_summary([r for r in scored['cases'] if r['case'].endswith('/root') and suite.certificates[r['fixture']]['condition']==condition and r['split']==split],'OL'),
            primary={key:cluster_summary(rows,key) for key in ('belief_exact','false_exclusions','unsupported_possibilities','OL','belief_repair')},
            R={key:cluster_summary(rows,key) for key in ('OO','OL','LO','LL')},
            channel_information_repair=cluster_summary(active,'channel_information_repair'),
            active_repairs={key:cluster_summary(active,key) for key in ('chooser_repair','updater_repair_model_action','updater_repair_oracle_action','oracle_action_belief_exact','model_action_belief_exact')},
            J={key:cluster_summary([dict(game=r['game'],**r.get('J',{})) for r in active],key) for key in ('OO','OL','LO','LL')})
    summary['coverage']=dict(requested=len(suite.tasks),valid=sum(records.get(t['id'],{}).get('status')=='ok' for t in suite.tasks),
                             unavailable_reference_costs=sum('LO_unavailable' in r for r in scored['cases']),
                             expected_model_action_arms=len(suite.fixtures),observed_model_action_arms=sum('model' in a for a in suite.arms.values()),
                             complete_J_tables=sum(len(r.get('J',{}))==4 for r in scored['active']))
    summary['belief_repair_interpretation']='Paired replacement of explicit partner judgment with identical public history, state and actions in fresh contexts. The planner may re-infer beliefs from history; a null repair effect does not establish absence of belief dependence.'
    summary['counterfactual_reference_limit']='A supplied wrong judgment can assign probability to types incompatible with public history. If this makes the history-aware reference undefined, LO and corresponding J entries are unavailable, never zero-filled. Direct paired LLM action regret, belief accuracy and channel scores remain defined.'
    summary['planning_interpretation']='Oracle-judgment-assisted planning with public history, not a pure planning deficit isolated from belief computation.'
    summary['scope']='Selected native positions; at most two measured ego decisions, without skipping native ego responses, and with reference continuation after the second measured action. Not an end-to-end LLM game outcome. Information-channel changes do not alone establish an information-mediated utility effect.'
    dump(out/'summary.json',summary)
    lines=['# Native BENAC-P diagnosis','',summary['mode'],'',summary['scope'],'',summary['planning_interpretation'],'',summary['belief_repair_interpretation'],'',summary['counterfactual_reference_limit'],'',
           'Measurement coverage: '+str(summary['coverage']),'',
           'Selection readiness: '+str(selection_readiness(suite,args.min_games_per_condition)),'',
           'Partner optimality is a best response to the exported fixed reference continuation, not an equilibrium. Confidence intervals cluster positions by original generated game seed. No model-performance filtering is applied.','']
    for condition,metrics in summary['conditions'].items():
        lines += ['## '+condition,'','| Metric | Mean | 95% interval | Games |','|---|---:|---|---:|']
        for name,x in dict(metrics['primary'],root_planning_regret=metrics['root_planning_regret'],channel_information_repair=metrics['channel_information_repair'],**metrics['active_repairs']).items():
            lines.append(f"| {name} | {x['mean']} | {x['ci95']} | {x['n_games']} |")
        for table in ('R','J'):
            cells=metrics[table]
            first,second,quantity=('belief','planner','regret; lower is better') if table=='R' else ('action chooser','belief updater','utility; higher is better; reference continuation planner')
            lines += ['',table+' four-cell decomposition ('+quantity+'):','',
                      f'| | Reference {second} | Model {second} |','|---|---:|---:|',
                      f"| Reference {first} | {cells['OO']['mean']} | {cells['OL']['mean']} |",
                      f"| Model {first} | {cells['LO']['mean']} | {cells['LL']['mean']} |",'']
    (out/'report.md').write_text('\n'.join(lines)+'\n')
    print(f'Completed {summary["mode"]}: {out}',flush=True)


if __name__=='__main__':main()
