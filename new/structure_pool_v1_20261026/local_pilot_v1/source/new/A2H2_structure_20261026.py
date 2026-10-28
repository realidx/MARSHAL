"""Read-only action/goal and information-use diagnosis of the frozen A2H2 pool."""
import os
for _key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[_key]='1'
import argparse
from collections import Counter,defaultdict
from functools import lru_cache
import gzip
from itertools import permutations,product
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'third_party/negotiation_benchmark/src'))
sys.path.insert(0,str(ROOT))
import numpy as np
from new.three_player_complexity_v1_20261023 import common as c
from new.strategic_game_v1_20261021.rules import StrategicRules
from training.b_sft.social_private_teacher import observed_slots
from training.strategic_slices.bounded import BoundedPrivateWindow
from new.node_qs_audit_v1_20261023.metrics import contingent_values
from training.strategic_slices.equilibrium import _reach

VERSION='A2H2-action-goal-structure-audit-v1'
REG=ROOT/'examples/strategic_slices/versions/A2H2_structure_v1_20261026/SNAPSHOT.json'
EPS=1e-8


class IndexedReference:
    """Count subtree lengths to recover selected preorder nodes and policy slices.

    Cache only geometric counts. Full histories and all native observations are
    reconstructed by actual actions; no information sets or policies are merged.
    """
    def __init__(self,job,flat=None):
        self.job=job;self.rules=StrategicRules(job['raw']);self.w=len(self.rules.worlds)
        self.flat=flat;self.hidden=[sum(len({r[g]for r in self.rules.catalogues[p]})>1
            for g in range(len(self.rules.spec.goals)))for p in range(self.rules.spec.n_players)]
        self.count=lru_cache(None)(self._count)
        self.nodes,self.floats=self.stats(self.rules.initial())
        assert self.nodes==job['preflight']['public_histories']
        if flat is not None:assert self.floats==len(flat)

    def _count(self,turn,masks,queries,offers):
        if turn==len(self.rules.spec.round_robin):return 1,0
        actor=self.rules.spec.round_robin[turn];na=1
        nodes,floats=self.count(turn+1,masks,queries,offers);nodes+=1
        if queries[actor]<self.rules.query_limit:
            m=max(0,sum(self.hidden)-self.hidden[actor]-queries[actor])
            q=list(queries);q[actor]+=1
            nn,nf=self.count(turn+1,masks,tuple(q),offers)
            nodes+=m*nn;floats+=m*nf;na+=m
        if offers[actor]<self.rules.offer_limit:
            used=list(offers);used[actor]+=1
            nr,fr=self.count(turn+1,masks,queries,tuple(used))
            for partner in range(self.rules.spec.n_players):
                if partner==actor:continue
                options=[[0]+[1<<a for a in range(self.rules.spec.n_actions_per_player[p])
                    if not(masks[p]&(1<<a))]for p in (actor,partner)]
                for own,other in product(*options):
                    if own==other==0:continue
                    updated=list(masks);updated[actor]|=own;updated[partner]|=other
                    nc,fc=self.count(turn+1,tuple(updated),queries,tuple(used))
                    nodes+=1+nr+nc;floats+=2*self.w+fr+fc;na+=1
        return nodes,floats+na*self.w

    def stats(self,node):
        state=node.state
        if node.pending is not None:
            values=[self.stats(self.rules._apply(node,a))for a in self.rules.actions(node)]
            return 1+sum(x[0]for x in values),2*self.w+sum(x[1]for x in values)
        masks=tuple(sum(int(v)<<a for a,v in enumerate(row))for row in state.snapshot_commitments())
        return self.count(state.turn_index,masks,tuple(state.query_used),tuple(state.offer_used))

    def find(self,target):
        assert 0<=target<self.nodes
        node=self.rules.initial();index=offset=0
        while index!=target:
            actions=self.rules.actions(node);ni=index+1;nf=offset+len(actions)*self.w
            for action in actions:
                child=self.rules._apply(node,action);nn,ff=self.stats(child)
                if ni<=target<ni+nn:
                    node,index,offset=child,ni,nf;break
                ni+=nn;nf+=ff
            else:raise AssertionError((target,index))
        return node,offset

    def replay(self,row,max_nodes,seconds):
        node,offset=self.find(row['node'])
        assert self.rules.actor(node)==row['actor'] and node.state.turn_index==row['turn']
        assert [a.to_dict()for a in self.rules.actions(node)]==row['actions']
        ids=[wi for wi,m in zip(row['world_ids'],row['posterior'])if m>0]
        weights=[m for m in row['posterior']if m>0]
        tree=BoundedPrivateWindow(self.rules,node,[self.rules.worlds[i]for i in ids],
            world_weights=weights,lookahead_rr=3,max_nodes=max_nodes,seconds=seconds)
        assert not tree.cutoff_leaves
        pos=offset
        for e,p in zip(tree.entries,tree.policy):
            if p is None:continue
            size=len(e.actions)*self.w
            p[:]=self.flat[pos:pos+size].reshape(len(e.actions),self.w)[:,ids];pos+=size
        assert pos==offset+self.stats(node)[1]
        tree.deadline=float('inf');values=contingent_values(tree,row['actor'],_reach(tree,row['actor']))
        q=np.array(weights)@np.stack([values[ch][:,row['actor']]for ch in tree.entries[0].children]).T
        np.testing.assert_allclose(q,row['Q'],atol=1e-7,rtol=0)
        return node,dict(nodes=len(tree.entries),Q_replay=q.tolist(),matches=True,
            commitments=node.state.snapshot_commitments(),
            query_used=node.state.query_used,offer_used=node.state.offer_used,
            history=[e.to_dict()for e in node.state.transcript])


def canonical_geometry(raw,typed):
    g=raw['game'];n=g['n_players'];keys=[]
    for perm in permutations(range(n)):
        for flips in product(*[range(2)if k==2 else range(1)for k in g['n_actions_per_player']]):
            actions=sorted((perm[p],k)for p,k in enumerate(g['n_actions_per_player']))
            edges=[]
            for goal in g['goals']:
                edge=sorted((perm[a['player_id']],a['action_id']^flips[a['player_id']])for a in goal['required_actions'])
                edges.append((goal['binary']if typed else None,edge))
            keys.append(c.stable([actions,sorted(edges,key=c.stable)]))
    return min(keys)


def geometry(job):
    raw=job['raw'];g=raw['game'];n=g['n_players'];ng=len(g['goals'])
    supports=[[sorted({row[k]for row in raw['type_catalogues'][str(p)]})for k in range(ng)]for p in range(n)]
    public={p:rows[0]for p in range(n)if len(rows:=raw['type_catalogues'][str(p)])==1}
    incidence={f'{p}:{a}':[i for i,x in enumerate(g['goals'])if any(z['player_id']==p and z['action_id']==a for z in x['required_actions'])]
        for p in range(n)for a in range(g['n_actions_per_player'][p])}
    return dict(original_index=job['original_index'],goals=g['goals'],actions=g['n_actions_per_player'],
        hidden_cells=[(p,k)for p in range(n)for k in range(ng)if len(supports[p][k])>1],
        preferences=raw['type_catalogues'],public_all_want=[p for p,row in public.items()if all(v==1 for v in row)],
        public_nonnegative_beneficiaries=[p for p,row in public.items()if all(v>=0 for v in row)and sum(v>0 for v in row)>=2],
        players_with_possible_all_want=[p for p in range(n)if any(all(v==1 for v in row)for row in raw['type_catalogues'][str(p)])],
        binary_goals=sum(x['binary']for x in g['goals']),linear_goals=sum(not x['binary']for x in g['goals']),
        incidence=incidence,action_change=job['changes']['action_change'],
        geometry_key=canonical_geometry(raw,False),typed_geometry_key=canonical_geometry(raw,True))


def group_key(row,mask):
    other=[a for a in row['private_answers']if a[:2]!=mask[1:]]
    return c.stable([row['node'],row['actor'],row['own_type'],other,mask])


def terminal_decomposition(indexed,row,node):
    if node.state.turn_index!=len(indexed.rules.spec.round_robin)-1 or node.pending is not None:return None
    rules=indexed.rules;worlds=rules.worlds;focal=row['actor'];base=node.state.goal_satisfaction();result=[]
    lookup={o['action']:o for o in row.get('offers',[])}
    for ai,action in enumerate(rules.actions(node)):
        if action.to_dict().get('action')!='OFFER':continue
        response=rules._apply(node,action);responses=rules.actions(response)
        accept=next(a for a in responses if a.to_dict()['response']=='ACCEPT')
        accepted=rules._apply(response,accept);delta=accepted.state.goal_satisfaction()-base
        partner=action.offer.partner_id;cases=[];qlo=qhi=0.
        for wi,m in zip(row['world_ids'],row['posterior']):
            if m<=0:continue
            world=worlds[wi];own=float(np.dot(world[partner],delta))
            compatible=[w for w in worlds if w[partner]==world[partner]and all(w[p][g]==world[p][g]for p,g in observed_slots(response,partner))]
            social=[float(sum(np.dot(w[p],delta)for p in range(rules.spec.n_players)if p!=partner))for w in compatible]
            if own>EPS:lo=hi=1.;reason='strict_own_accept'
            elif own<-EPS:lo=hi=0.;reason='strict_own_reject'
            elif min(social)>EPS:lo=hi=1.;reason='own_tie_robust_social_accept'
            elif max(social)<-EPS:lo=hi=0.;reason='own_tie_robust_social_reject'
            else:lo=0.;hi=1.;reason='social_belief_or_remaining_tie_not_resolved'
            u0=float(np.dot(world[focal],base));du=float(np.dot(world[focal],delta))
            qlo+=m*min(u0+lo*du,u0+hi*du);qhi+=m*max(u0+lo*du,u0+hi*du)
            cases.append(dict(world_id=wi,posterior=m,partner_type=world[partner],
                partner_own_gain=own,own_gain_by_goal=(np.array(world[partner])*delta).tolist(),
                other_gain_range=[min(social),max(social)],acceptance_bounds=[lo,hi],reason=reason))
        assert qlo-1e-7<=row['Q'][ai]<=qhi+1e-7
        o=lookup[ai];expected=o['Q_reject']+o['acceptance']*(o['Q_accept']-o['Q_reject'])
        assert abs(expected-row['Q'][ai])<1e-7
        result.append(dict(action=ai,offer=action.to_dict(),goal_satisfaction_delta=delta.tolist(),
            Q=row['Q'][ai],acceptance=o['acceptance'],own_accept=o['Q_accept'],own_reject=o['Q_reject'],
            independent_Q_bounds=[qlo,qhi],strictly_reconstructed=abs(qhi-qlo)<1e-7,cases=cases))
    return result


def rows_from(folder):
    with gzip.open(folder/'labels.jsonl.gz','rt')as stream:
        for line in stream:yield json.loads(line)


def analyze(job,result,folder,args):
    started=time.monotonic();positive=[];best={};counts=Counter();turns=Counter()
    def rank(row,score):return score,row['reference_mass'],-row['node'],-row['cell']
    for row in rows_from(folder):
        counts['contexts']+=1
        if max(row['S_private'],row['S_history'])>EPS:
            positive.append(row);turns[f'{row["actor"]}:{row["phase"]}:{row["turn"]}']+=1
        if row['phase']!='proposal':continue
        for item in row['S_items']:
            if item['S']>EPS:
                label=item['omitted'][0]
                if label not in best or rank(row,item['S'])>best[label][0]:best[label]=(rank(row,item['S']),row,item)
            if item['omitted'][0]=='private'and item.get('full_contexts',1)>1:
                if 'control'not in best or rank(row,row['span'])>best['control'][0]:best['control']=(rank(row,row['span']),row,item)
    with np.load(folder/'reference.npz')as data:flat=data['probabilities']
    indexed=IndexedReference(job,flat);examples=json.load(open(folder/'examples.json'));validated=0
    for exampleset in examples.values():
        for ex in exampleset:
            node,_=indexed.find(ex['node'])
            assert c.stable(node.state.snapshot_commitments())==c.stable(ex['commitments'])
            assert [e.to_dict()for e in node.state.transcript]==ex['history']
            assert (None if node.pending is None else node.pending.to_dict())==ex['pending']
            assert [a.to_dict()for a in indexed.rules.actions(node)]==ex['actions'];validated+=1
    families=Counter();by_actor=Counter()
    for row in positive:
        node,_=indexed.find(row['node']);by_actor[str(row['actor'])]+=1
        key=c.stable([row['actor'],row['phase'],row['turn'],node.state.snapshot_commitments(),node.state.query_used,node.state.offer_used,
            None if node.pending is None else node.pending.to_dict()])
        families[key]+=1
    selected=[best[k]for k in ('private','history')if k in best]if positive else ([best['control']]if 'control'in best else [])
    witness=[];replays=0
    for _,chosen,item in selected:
        mask=item['omitted'];members=[]
        if mask[0]=='private':
            key=group_key(chosen,mask)
            for row in rows_from(folder):
                if any(x['omitted']==mask for x in row['S_items'])and group_key(row,mask)==key:members.append(row)
            assert len(members)==item['full_contexts']
        else:members=[chosen]
        cases=[]
        for row in members:
            node,replay=indexed.replay(row,args.max_subtree_nodes,args.subtree_seconds);replays+=1
            cases.append(dict(row=row,replay=replay,terminal_decomposition=terminal_decomposition(indexed,row,node)))
        common=sorted(set.intersection(*(set(r['own_optimal'])for r in members)))
        mass=sum(r['counterfactual_mass']for r in members)
        mean=np.array([r['counterfactual_mass']for r in members])/mass
        Q=np.array([r['Q']for r in members]);gap=float(mean@Q.max(axis=1)-(mean@Q).max())
        if mask[0]=='private':
            assert common or gap>1e-12
            if not positive:assert common
        witness.append(dict(omitted=mask,positive_parent=bool(positive),common_current_own_optimum=common,
            same_Q_across_answers=bool(np.max(np.ptp(Q,axis=0))<1e-7),
            first_decision_information_gap=gap if mask[0]=='private'else None,
            note='First-decision gap restores full information after current choice; not main full-strategy S',cases=cases))
    return dict(original_index=job['original_index'],status='COMPLETED',positive_contexts=len(positive),
        positive_by_actor=by_actor,positive_by_actor_phase_turn=turns,physical_skeleton_count=len(families),
        physical_skeleton_multiplicities=sorted(families.values(),reverse=True),
        physical_skeleton_caution='Descriptive count only; histories and higher-order beliefs are not strategically merged',
        recovered_example_checks=validated,replay_checks=replays,selected_witnesses=witness,
        selection_status=('SELECTED'if selected else 'NO_POSITIVE_PROPOSAL'if positive else 'NO_AMBIGUOUS_PRIVATE_PROPOSAL'),
        elapsed_seconds=time.monotonic()-started)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run',type=Path,default=ROOT/'new/three_player_complexity_v1_20261023/local_A2H2_33_v1')
    parser.add_argument('--H2-run',type=Path,default=ROOT/'new/three_player_complexity_v1_20261023/local_H2_33_v1')
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--max-subtree-nodes',type=int,default=50000)
    parser.add_argument('--subtree-seconds',type=float,default=30.);args=parser.parse_args()
    jobs=json.load(open(args.run/'jobs.json'));results=json.load(open(args.run/'results.json'));byid={r['index']:r for r in results}
    h2=json.load(open(args.H2_run/'jobs.json'));inputs={}
    for run,name in [(args.run,'A2H2'),(args.H2_run,'H2')]:
        for f in ('pipeline_snapshot.json','COMPLETE.json','jobs.json','results.json'):inputs[f'{name}:{f}']=c.identity(run/f)
    for r in results:
        if r.get('labels')!='MEASURED':continue
        folder=args.run/Path(r['result_path']).parent
        for f,key in [('reference.npz','reference_sha256'),('labels.jsonl.gz','labels_sha256'),('examples.json','examples_sha256')]:
            assert c.sha(folder/f)==r[key];inputs[f'{r["index"]}:{f}']=c.identity(folder/f)
    c.VERSION,c.REG=VERSION,REG
    c.snapshot(args.output,dict(operation='Read-only action-goal structural diagnosis on all33 A2H2 parents',
        run=str(args.run),H2_run=str(args.H2_run),max_subtree_nodes=args.max_subtree_nodes,subtree_seconds=args.subtree_seconds,
        EPS=EPS,selection='All33 geometry; all30 measured labels; 3 missing unchanged',
        examples='Each positive parent maximal private/history proposal witness; each zero parent maximal-span ambiguous-private proposal group',
        native_recovery='Exact subtree node/flat-policy counts to recover preorder root; verify saved example histories/states/actions and full flat length',
        replay='Selected native remaining subtrees to actual terminal, frozen saved opponent profile, focal full-information contingent BR; no new equilibrium',
        first_decision_gap='Counterfactual-weighted E max Q minus max E Q within same-node private group; diagnostic only',
        terminal_bounds='Last proposal only; strict responder-own signs, then social signs robust to every world compatible with own type/direct answers; unresolved cases bounded',
        physical_skeleton='Count only, do not merge strategic histories or change labels',
        feature_scope='Post-hoc explanatory associations after inspecting62/78; not independent validation or a new generator',
        sys_path=list(sys.path),workers=1,model='NOT_USED',D='NOT_MEASURED',training='NOT_RUN',production='UNCHANGED_V8'),inputs)
    geometries=[geometry(j)for j in jobs];hgeom=[geometry(j)for j in h2]
    for g in geometries:
        rr=next(r for r in results if r['original_index']==g['original_index'])
        g['label_status']=rr.get('labels');g['positive_parent']=None if rr.get('labels')!='MEASURED'else bool(rr['summary']['counterfactual']['private_S_positive']or rr['summary']['counterfactual']['history_S_positive'])
        g['same_untyped_geometry']=[x['original_index']for x in geometries if x['geometry_key']==g['geometry_key']]
        g['same_typed_geometry']=[x['original_index']for x in geometries if x['typed_geometry_key']==g['typed_geometry_key']]
    c.write(args.output/'GEOMETRY.json',dict(A2H2=geometries,H2=hgeom))
    records=[]
    for job in jobs:
        r=byid[job['index']]
        if r.get('labels')!='MEASURED':
            records.append(dict(original_index=job['original_index'],status='LABEL_UNAVAILABLE',solver_status=r['status']));continue
        folder=args.run/Path(r['result_path']).parent
        result=analyze(job,r,folder,args);records.append(result)
        c.write(args.output/'cases'/f'{job["original_index"]}.json',result)
        print({k:result[k]for k in ('original_index','positive_contexts','physical_skeleton_count','replay_checks','elapsed_seconds')},flush=True)
    c.write(args.output/'RESULTS.json',records)
    counts=Counter();assoc={}
    measured=[g for g in geometries if g['positive_parent']is not None]
    for feature,predicate in [('public_all_want',lambda g:bool(g['public_all_want'])),('all_linear',lambda g:g['binary_goals']==0),
        ('public_nonnegative_beneficiary',lambda g:bool(g['public_nonnegative_beneficiaries']))]:
        assoc[feature]={}
        for value in (False,True):
            group=[g for g in measured if predicate(g)==value]
            assoc[feature][str(value)]=dict(parents=len(group),own_S_positive=sum(g['positive_parent']for g in group),original_indices=[g['original_index']for g in group])
    for result in records:
        if result['status']!='COMPLETED':continue
        for k in ('positive_contexts','physical_skeleton_count','recovered_example_checks','replay_checks'):counts[k]+=result[k]
        for witness in result['selected_witnesses']:
            for case in witness['cases']:
                for offer in case['terminal_decomposition']or []:
                    counts['terminal_offer_bounds_checked']+=1;counts['terminal_offer_Q_independently_reconstructed']+=offer['strictly_reconstructed']
    c.write(args.output/'SUMMARY.json',dict(measured=30,unavailable=[10,49,76],counts=counts,associations=assoc,
        focus_geometry={str(i):next(g for g in geometries if g['original_index']==i)for i in (62,78)},
        main_Q_S='UNCHANGED',game_and_generation='UNCHANGED',D='NOT_MEASURED',production='UNCHANGED_V8'))
    c.write(args.output/'COMPLETE.json',dict(completed=True,measured=30,missing=3,counts=counts,
        summary_sha256=c.sha(args.output/'SUMMARY.json'),results_sha256=c.sha(args.output/'RESULTS.json'),
        geometry_sha256=c.sha(args.output/'GEOMETRY.json'),pipeline_snapshot_sha256=c.sha(args.output/'pipeline_snapshot.json')))


if __name__=='__main__':main()
