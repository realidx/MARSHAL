"""Verify query answer gain equals weighted existing privateS at next decisions."""
from new import query_answer_access_20261104 as q
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
import gzip
import json
from pathlib import Path
import time
import traceback
import numpy as np

p=q.p
VERSION='strict-query-answer-chain-verification-v1'
REG=p.m.ROOT/'examples/strategic_slices/versions/query_answer_chain_v1_20261104/SNAPSHOT.json'


def info_key(index,world,slots,focal):
    return p.stable([index,world[focal],[(a,g,world[a][g])for a,g in slots]])


def first_contexts(sparse,row,action_result):
    ai=action_result['action_index'];_,_,_,children=sparse.expand(row['node'])
    _,root,_=children[ai];focal=row['actor'];prior=np.zeros(sparse.w)
    prior[row['world_ids']]=row['posterior'];todo=[(root,prior)];groups={};terminal_mass=terminal_value=0.
    while todo:
        gi,mass=todo.pop();node,offset=sparse.locate(gi);actor=sparse.rules.actor(node)
        if actor is None:
            terminal_mass+=float(mass.sum())
            terminal_value+=float(mass@np.einsum('wg,g->w',sparse.types[:,focal],node.state.goal_satisfaction()))
        elif actor==focal:
            slots=tuple(p.observed_slots(node,focal))
            for wi in np.flatnonzero(mass>0):
                key=info_key(gi,sparse.worlds[wi],slots,focal)
                if key not in groups:groups[key]=dict(node=gi,mass=0.,world_masses={})
                groups[key]['mass']+=float(mass[wi]);groups[key]['world_masses'][str(int(wi))]=float(mass[wi])
        else:
            _,_,actions,children=sparse.expand(gi)
            policy=sparse.flat[offset:offset+len(actions)*sparse.w].reshape(len(actions),sparse.w)
            for ai,(_,child,_)in enumerate(children):
                m=mass*policy[ai]
                if np.any(m>0):todo.append((child,m))
    assert abs(terminal_mass+sum(x['mass']for x in groups.values())-1)<1e-8
    return dict(groups=groups,terminal_mass=terminal_mass,terminal_value=terminal_value)


def worker(parent,channel,pool,out):
    started=time.monotonic();result=dict(index=parent['index'],source_key=parent['source_key'],players=parent['players'],entries=[])
    try:
        assert channel['status']=='COMPLETED'
        assert p.m.sha(p.m.ROOT/parent['admission']['path'])==parent['admission']['sha256']
        source=json.loads((p.m.ROOT/parent['admission']['path']).read_text())['source']
        assert p.digest(source['job']['raw'])==parent['source_raw_sha256']
        assert p.m.sha(pool/parent['reference']['path'])==parent['reference']['sha256']
        with np.load(pool/parent['reference']['path'])as data:flat=data['probabilities']
        indexed=p.IndexedReference(source['job'],flat);sparse=p.sparse_impl.SparseNative(indexed,8192)
        paths=[];needed=set()
        for entry in channel['entries']:
            assert entry['status']=='VERIFIED'
            for action in entry['queries']:
                path=first_contexts(sparse,entry,action)
                for group in path['groups'].values():needed.add(group['node'])
                paths.append((entry,action,path))
        labels={}
        assert p.m.sha(pool/parent['labels']['path'])==parent['labels']['sha256']
        with gzip.open(pool/parent['labels']['path'],'rt')as stream:
            for line in stream:
                row=json.loads(line)
                if row['node']not in needed or row['counterfactual_mass']<=0:continue
                key=p.stable([row['node'],row['own_type'],row['private_answers']]);assert key not in labels
                labels[key]=row
        for entry,action,path in paths:
            full=blind=path['terminal_value'];weighted_S=0.;witnesses=[]
            mask=['private',action['action']['player'],action['action']['goal']]
            for key,group in path['groups'].items():
                row=labels[key];mass=group['mass']
                # The pre-query and global counterfactual beliefs must agree
                # after conditioning on this first full-information context.
                actual={str(w):float(m)for w,m in zip(row['world_ids'],row['posterior'])if m>0}
                expected={w:m/mass for w,m in group['world_masses'].items()}
                assert actual.keys()==expected.keys()
                assert max(abs(actual[w]-expected[w])for w in actual)<1e-8
                item=next(x for x in row['S_items']if x['omitted']==mask)
                full+=mass*max(row['Q']);blind+=mass*(max(row['Q'])-item['S']);weighted_S+=mass*item['S']
                witnesses.append(dict(node=row['node'],cell=row['cell'],mass=mass,private_S=item['S'],
                    current_loss=item['own_current_loss'],future_loss=item['own_future_loss']))
            full_error=abs(full-action['full']);blind_error=abs(blind-action['answer_suppressed'])
            gain_error=abs(weighted_S-action['private_answer_increment'])
            assert max(full_error,blind_error,gain_error)<1e-7,(entry['index'],entry['node'],action['action'],full,blind,weighted_S,action)
            result['entries'].append(dict(entry_id=entry['entry_id'],node=entry['node'],cell=entry['cell'],
                category=entry['category'],action_index=action['action_index'],action=action['action'],
                full_from_next_contexts=full,blind_from_next_contexts=blind,
                weighted_existing_private_S=weighted_S,private_answer_increment=action['private_answer_increment'],
                absolute_errors=dict(full=full_error,blind=blind_error,gain=gain_error),
                terminal_before_next_focal_mass=path['terminal_mass'],next_contexts=witnesses,
                all_conditional_beliefs_match=True))
        result['status']='VERIFIED'
    except Exception as exc:
        result.update(status='ERROR',error=f'{type(exc).__name__}: {exc}',traceback=traceback.format_exc())
    result['elapsed_seconds']=time.monotonic()-started
    p.m.write(out/'cases'/str(parent['index'])/'RESULT.json',result)
    print(dict(index=parent['index'],status=result['status'],branches=len(result['entries']),seconds=round(result['elapsed_seconds'],2)),flush=True)
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--pool',type=Path,required=True)
    parser.add_argument('--channels',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--workers',type=int,default=2);args=parser.parse_args()
    for key in ('pool','channels','output'):setattr(args,key,getattr(args,key).resolve())
    complete=json.loads((args.channels/'COMPLETE.json').read_text())
    assert p.m.sha(args.channels/'RESULTS.json')==complete['results_sha256']
    assert not complete['parent_errors']and complete['unavailable_query_actions']==0
    parents=[json.loads(x)for x in(args.pool/'parents.jsonl').read_text().splitlines()]
    results=json.loads((args.channels/'RESULTS.json').read_text())
    p.VERSION,p.REG=VERSION,REG
    p.snapshot(args.output,dict(operation='Independent native first-decision traversal and chain identity to existing mainS',
        workers=args.workers,all_parent_indices=[x['index']for x in results],
        equation='Query full-blind = sum(first-next full-context probability * existing private-answer S)',
        root_information='Existing pre-query own type+direct answers and CF belief; no model sampling',
        belief_check='Normalized conditional first-context masses must match saved main-label posterior',
        native_traversal='Only opponents until first focal decision; no new optimization or newQ/S',
        match_tolerance=1e-7,cache_nodes=8192,selection800='NOT_RUN'),
        dict(pool=p.ident(args.pool/'MANIFEST.json'),parents=p.ident(args.pool/'parents.jsonl'),
             channels=p.ident(args.channels/'RESULTS.json'),channel_complete=p.ident(args.channels/'COMPLETE.json')))
    output=[]
    with ProcessPoolExecutor(max_workers=args.workers)as executor:
        fs=[executor.submit(worker,parents[r['index']],r,args.pool,args.output)for r in results]
        for future in as_completed(fs):
            output.append(future.result());output.sort(key=lambda x:x['index']);p.m.write(args.output/'RESULTS.json',output)
    branches=[e for c in output for e in c['entries']]
    summary=dict(parents=len(output),verified_parents=sum(c['status']=='VERIFIED'for c in output),
        errors=[dict(index=c['index'],error=c['error'])for c in output if c['status']!='VERIFIED'],
        branches=len(branches),next_full_context_occurrences=sum(len(e['next_contexts'])for e in branches),
        max_absolute_errors={name:max(e['absolute_errors'][name]for e in branches)for name in ('full','blind','gain')},
        positive_existing_S_branch=sum(e['weighted_existing_private_S']>p.m.EPS for e in branches),
        scope='Verification of fixed-reference answer-access to existing privateS identity, not new labels or final selection')
    p.m.write(args.output/'SUMMARY.json',summary)
    p.m.write(args.output/'COMPLETE.json',dict(**summary,results_sha256=p.m.sha(args.output/'RESULTS.json'),
        summary_sha256=p.m.sha(args.output/'SUMMARY.json'),pipeline_snapshot_sha256=p.m.sha(args.output/'pipeline_snapshot.json')))


if __name__=='__main__':main()
