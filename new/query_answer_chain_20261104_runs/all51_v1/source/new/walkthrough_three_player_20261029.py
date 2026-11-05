"""One actual frozen parent: native replay, terminal-Q decomposition and S LP."""
import argparse
from collections import defaultdict
from fractions import Fraction
import gzip
import io
import json
from pathlib import Path
import tarfile

from new import structure_pool_20261026 as p
from new.A2H2_structure_20261026 import IndexedReference
from new.node_qs_audit_v1_20261023.metrics import Observations,contingent_values,forest_response
from new.node_qs_audit_v1_20261023.witness import sequence_lp
from training.strategic_slices.bounded import BoundedPrivateWindow
from training.strategic_slices.equilibrium import _reach
import numpy as np

VERSION='three-player-case-walkthrough-v1'
REG=p.ROOT/'examples/strategic_slices/versions/three_player_case_walkthrough_v1_20261029/SNAPSHOT.json'
INDEX=10
NODE=151856
RUN='runtime/new/structure_pool_v1_20261026/remote_remaining18_runtime_v4_20261029/'


def identity(path):return dict(path=str(path.relative_to(p.ROOT)),sha256=p.sha(path))
def rational(x):return str(Fraction(float(x)).limit_denominator(1000000))


def view(rules,node,world,player):
    fixed=[]
    for pp,rows in rules.catalogues.items():
        for g in range(len(rules.spec.goals)):
            values={row[g]for row in rows}
            if len(values)==1:fixed.append(dict(player=pp,goal=g,value=next(iter(values))))
    return dict(kind='Environment facts only; NOT a generated LLM messages/tools request',
        public_rules=rules.public_game(),public_preferences=fixed,
        observation=rules.observation(node,player,world[player]),
        legal_native_actions=[a.to_dict()for a in rules.actions(node)])


def advance(indexed,node,index,action):
    cursor=index+1
    for candidate in indexed.rules.actions(node):
        child=indexed.rules._apply(node,candidate)
        if candidate==action:return child,cursor
        cursor+=indexed.stats(child)[0]
    raise AssertionError('Native action not found')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--max-nodes',type=int,default=10000);parser.add_argument('--seconds',type=float,default=30.)
    args=parser.parse_args();args.output=args.output.resolve()
    root=p.ROOT;bundle=root/'new/structure_pool_remote_results_20261029'
    pool=root/'new/structure_pool_v1_20261026/raw_v1/parents.jsonl'
    prior=root/'new/structure_pool_return_audit_20261029/run_v1'
    inputs={str(q.relative_to(root)):identity(q)for q in [pool,bundle/'results.tar.gz',bundle/'MANIFEST.json',prior/'PARENTS.json',prior/'COMPLETE.json',prior/'pipeline_snapshot.json']}
    p.VERSION,p.REG=VERSION,REG
    p.snapshot(args.output,dict(operation='One-game explanatory audit, no new game/selection/prompt or equilibrium search',
        index=INDEX,node=NODE,world='Supported world0: P0/G2=want and P2/G2=want; chosen for this already-saved witness, not a generator constraint',
        max_nodes=args.max_nodes,construct_seconds=args.seconds,LP='Existing sequence-form LP,60s per solve, own-payoff relaxation for conservative target bounds',
        prefix='Exactly the previously saved witness public history; realized private answers delivered by native step',
        tails='All positive-probability frozen-reference suffixes for root actions8 and4, conditioned on world0; compare with saved Q_reference and Q',
        answers='All positiveCF full contexts at same node/own type, merge only one private answer, preserve full public history and all other facts',
        length='Report actual focal decision counts on reconstructed paths only; no new k default or distribution',
        workers=1,threads=1,model='NOT_USED',D='NOT_MEASURED',training='NOT_RUN',new_prompt='NOT_RENDERED_NOT_CHANGED',candidate800='NOT_GENERATED'),inputs)
    jobs=list(map(json.loads,pool.read_text().splitlines()));job=jobs[INDEX]
    regenerated=p.generate_pair(job['pair_id'],**{k:job['configuration'][k]for k in ('goals','geometry','scoring')})
    assert regenerated[0]['raw']==job['raw']and regenerated[0]['id']==job['id']
    manifest=json.loads((bundle/'MANIFEST.json').read_text());assert p.sha(bundle/'results.tar.gz')==manifest['archive']['sha256']
    original={x['path']:x for x in manifest['files']}
    with tarfile.open(bundle/'results.tar.gz')as tar:
        def read(name):
            data=tar.extractfile(name).read()
            import hashlib
            assert hashlib.sha256(data).hexdigest()==original[name]['sha256'],name
            return data
        results=json.loads(read(RUN+'results.json'));result=next(x for x in results if x['index']==INDEX)
        folder=RUN+str(Path(result['result_path']).parent)
        labels=gzip.decompress(read(folder+'/labels.jsonl.gz'))
        reference=read(folder+'/reference.npz');request=json.loads(read(folder+'/request.json'))
        assert request['job']==job and result['cutoff_leaves']==0
        remote_config=json.loads(read(RUN+'pipeline_snapshot.json'))
    rows=list(map(json.loads,labels.splitlines()));chosen=next(r for r in rows if r['node']==NODE and r['cell']==0)
    assert chosen['own_type']==[0,1,1]and chosen['private_answers']==[[2,2,1]]
    previous=next(x for x in json.loads((prior/'PARENTS.json').read_text())if x['index']==INDEX)
    prefix=previous['replay_checks'][0]['check']['history']
    with np.load(io.BytesIO(reference))as npz:flat=npz['probabilities']
    indexed=IndexedReference(job,flat);rules=indexed.rules;world=rules.worlds[0]
    assert world[0]==(0,1,1)and world[2]==(-1,0,1)
    public=rules.initial();real=rules.initial();ni=0;steps=[];before_query=None
    for event in prefix:
        if event['action']=='OFFER':wanted=dict(action='OFFER',**event['offer'])
        elif event['action']=='INVESTIGATE':wanted={k:event[k]for k in ('action','player','goal')}
        else:wanted=dict(action='PASS')
        if event['action']=='INVESTIGATE'and event['proposer_id']==0:before_query=ni
        sequence=[wanted]+([dict(response=event['response'])]if event.get('response')else[])
        for wanted in sequence:
            action=next(a for a in rules.actions(public)if a.to_dict()==wanted)
            actor=rules.actor(real);prob_index,offset=indexed.find(ni)
            probs=flat[offset:offset+len(rules.actions(public))*indexed.w].reshape(len(rules.actions(public)),indexed.w)[:,0]
            ai=list(rules.actions(public)).index(action)
            assert probs[ai]>0
            steps.append(dict(public_node=ni,turn=real.state.turn_index,actor=actor,
                phase='response'if real.pending else'proposal',action=wanted,
                reference_probability_given_world0=float(probs[ai]),visible_before=view(rules,real,world,actor)))
            public,ni=advance(indexed,public,ni,action)
            real=rules.step(real,action,realized_world=world)
            assert public.state.public_state()==real.state.public_state()
            steps[-1].update(commitments_after=real.state.snapshot_commitments(),
                query_used_after=real.state.query_used,offer_used_after=real.state.offer_used,
                private_results_after=real.state.private_results)
    assert ni==NODE and [list(x)for x in real.state.private_results[0]]==[[2,2,1]]
    assert [list(x)for x in real.state.private_results[1]]==[[0,2,1]]
    p.write(args.output/'CASE.json',dict(job=job,worlds=rules.worlds,realized_world_index=0,realized_world=world,
        generation_rebuild_matches=True,original_result=result,original_runtime=remote_config,
        dimensions=dict(public_nodes=indexed.nodes,worlds=indexed.w,terminal_leaves=result['native_audit']['terminal_leaves']),
        scope='Current24 index10, not original100 parent10; concrete research instance, not formal final-game default'))
    p.write(args.output/'PREFIX.json',steps)
    p.write(args.output/'VISIBLE_AT_ENTRY.json',view(rules,real,world,0))
    mask=('private',2,2)
    members=[r for r in rows if r['node']==NODE and r['actor']==0 and r['own_type']==chosen['own_type']
        and any(tuple(x['omitted'])==mask for x in r['S_items'])]
    assert len(members)==3
    masses=np.zeros(indexed.w)
    for row in members:masses[row['world_ids']]+=row['counterfactual_mass']*np.array(row['posterior'])
    ids=np.flatnonzero(masses>0).tolist();weights=masses[ids]/masses.sum();assert ids==[0,1,2]
    node,offset=indexed.find(NODE)
    tree=BoundedPrivateWindow(rules,node,[rules.worlds[i]for i in ids],world_weights=weights,
        lookahead_rr=3,max_nodes=args.max_nodes,seconds=args.seconds)
    assert not tree.cutoff_leaves
    pos=offset
    for entry,policy in zip(tree.entries,tree.policy):
        if policy is None:continue
        size=len(entry.actions)*indexed.w
        policy[:]=flat[pos:pos+size].reshape(len(entry.actions),indexed.w)[:,ids];pos+=size
    assert pos-offset==indexed.stats(node)[1]
    tree.deadline=float('inf');obs=Observations(tree,0);roots={0:weights}
    values=contingent_values(tree,0,_reach(tree,0));q=np.stack([values[ch][:,0]for ch in tree.entries[0].children]).T
    for row in members:
        wi=ids.index(row['world_ids'][0]);np.testing.assert_allclose(q[wi],row['Q'],atol=1e-7,rtol=0)
    full=forest_response(tree,0,roots,observations=obs)
    omitted=forest_response(tree,0,roots,omitted=mask,observations=obs)
    lp_full=sequence_lp(tree,0,roots,omitted=None,observations=obs)
    lp_omit=sequence_lp(tree,0,roots,omitted=mask,observations=obs,target=(0,{0}))
    assert abs(lp_full['V_omitted_LP']-float(weights@full['values'][0][:,0]))<1e-7
    assert abs(lp_omit['V_omitted_LP']-float(weights@omitted['values'][0][:,0]))<1e-7
    comparisons=[]
    for row in sorted(members,key=lambda r:r['world_ids'][0]):
        wi=ids.index(row['world_ids'][0]);s=max(row['Q'])-float(omitted['values'][0][wi,0])
        np.testing.assert_allclose(s,row['S_private'],atol=1e-7,rtol=0)
        comparisons.append(dict(answer=rules.worlds[ids[wi]][2][2],counterfactual_mass=row['counterfactual_mass'],
            answer_omitted_belief=float(weights[wi]),full_Q=row['Q'],full_own_optimal=row['own_optimal'],
            omitted_root_policy=omitted['root_policy'][0][:,wi].tolist(),
            full_value=float(full['values'][0][wi,0]),omitted_true_value=float(omitted['values'][0][wi,0]),S=s))
    lower=max(0.,max(chosen['Q'])-lp_omit['target_own_value_max'])
    upper=max(0.,max(chosen['Q'])-lp_omit['target_own_value_min'])
    assert lower-1e-7<=chosen['S_private']<=upper+1e-7
    p.write(args.output/'ANSWER_OMISSION.json',dict(original_row=chosen,answer_comparisons=comparisons,
        all3_Q_and_S_match=True,full_LP=lp_full,omitted_LP=lp_omit,
        chosen_context_S_interval=[lower,upper],remaining_native_nodes=len(tree.entries),
        contract='One private answer inaccessible at every future focal decision; same public query/history/physical state and fixed opponent policies; own prefix actions interventions'))
    tails=[]
    for ai in (8,4):
        first=tree.entries[0].actions[ai];after=rules.step(real,first,realized_world=world);paths=[]
        def walk(ei,current,mass,decisions):
            entry=tree.entries[ei]
            assert entry.node.state.public_state()==current.state.public_state()
            if entry.actor is None:
                utility=rules.terminal_payoffs(current,world)
                np.testing.assert_allclose(utility,entry.payoff[0],atol=1e-12,rtol=0)
                paths.append(dict(probability=mass,decisions=decisions,commitments=current.state.snapshot_commitments(),
                    goal_satisfaction=current.state.goal_satisfaction().tolist(),utilities=utility,
                    focal_decisions_in_suffix=sum(x['actor']==0 for x in decisions),
                    private_results=current.state.private_results));return
            for j,act in enumerate(entry.actions):
                probability=float(tree.policy[ei][j,0])
                if probability<=0:continue
                child=rules.step(current,act,realized_world=world)
                walk(entry.children[j],child,mass*probability,decisions+[dict(turn=current.state.turn_index,
                    actor=entry.actor,phase='response'if current.pending else'proposal',action=act.to_dict(),
                    conditional_probability=probability)])
        walk(tree.entries[0].children[ai],after,1.,[dict(turn=real.state.turn_index,actor=0,phase='proposal',action=first.to_dict(),conditional_probability=1.)])
        expected=sum(x['probability']*x['utilities'][0]for x in paths)
        assert abs(sum(x['probability']for x in paths)-1.)<1e-10
        assert abs(expected-chosen['Q'][ai])<1e-7
        grouped=defaultdict(lambda:dict(probability=0.,paths=0))
        for path in paths:
            key=p.stable([path['commitments'],path['utilities']]);g=grouped[key];g['probability']+=path['probability'];g['paths']+=1
            g.update(commitments=path['commitments'],utilities=path['utilities'],goal_satisfaction=path['goal_satisfaction'])
        tails.append(dict(root_action_index=ai,root_action=first.to_dict(),expected_focal_terminal_utility=expected,
            expected_fraction=rational(expected),all_positive_reference_paths=paths,terminal_outcomes=list(grouped.values())))
    p.write(args.output/'TERMINAL_CONTINUATIONS.json',tails)
    query=next(r for r in rows if r['node']==before_query and r['actor']==0 and r['own_type']==chosen['own_type'])
    p.write(args.output/'QUERY_ENTRY.json',query)
    p.write(args.output/'COMPLETE.json',dict(index=INDEX,node=NODE,generation_matches=True,prefix_legal=True,
        private_answers_persist=True,full_Q_context_checks=3,omitted_S_context_checks=3,LP_objective_checks=2,
        S_interval=[lower,upper],tail_actions_checked=[8,4],remaining_native_nodes=len(tree.entries),
        native_cutoff_leaves=len(tree.cutoff_leaves),query_node=before_query,query_gap=query['query_gap'],
        source_snapshot_sha256=p.sha(args.output/'pipeline_snapshot.json'),model_calls=0,D='NOT_MEASURED',
        prompt='NOT_RENDERED_NOT_CHANGED',candidate800='NOT_GENERATED',training='NOT_RUN'))
    print(p.stable(json.loads((args.output/'COMPLETE.json').read_text())),flush=True)


if __name__=='__main__':main()
