"""Fixed-reference answer access for every query at235 strict-query entries."""
from new import qualified_parents_6535_20261104 as p
from new import entry_supply_audit_20261104 as supply
from new.node_qs_audit_v1_20261023.metrics import forest_response, Observations
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import contextmanager
import gzip
import json
from pathlib import Path
import signal
import time
import traceback
import numpy as np

VERSION='strict-query-answer-access-v1'
REG=p.m.ROOT/'examples/strategic_slices/versions/query_answer_access_v1_20261104/SNAPSHOT.json'
NECESSARY='ANSWER_NEEDED_FOR_STRICT_QUERY_ADVANTAGE'
AMPLIFIES='ANSWER_IMPROVES_VALUE_BUT_BLIND_QUERY_STILL_STRICTLY_BETTER'
NO_INCREMENT='BEST_ENTRY_VALUE_ACHIEVABLE_WITHOUT_CURRENT_QUERY_ANSWER'
UNKNOWN='UNAVAILABLE_INCOMPLETE_QUERY_CHECKS'


@contextmanager
def timeout(seconds):
    def expired(signum,frame):raise TimeoutError('Per-action answer-access deadline')
    old=signal.signal(signal.SIGALRM,expired)
    signal.setitimer(signal.ITIMER_REAL,seconds)
    try:yield
    finally:
        signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,old)


def first_decision(tree,roots,focal,mask):
    obs=Observations(tree,focal);groups=defaultdict(Counter);terminal=0.
    stack=list(roots.items())
    while stack:
        i,mass=stack.pop();entry=tree.entries[i]
        if entry.actor is None:
            terminal+=float(mass.sum());continue
        if entry.actor==focal:
            for wi in np.flatnonzero(mass>0):
                groups[obs.key(i,int(wi),mask)][tree.worlds[wi][mask[1]][mask[2]]]+=float(mass[wi])
        else:
            for ai,child in enumerate(entry.children):
                m=mass*tree.policy[i][ai]
                if np.any(m>0):stack.append((child,m))
    total=sum(float(v.sum())for v in roots.values())
    decision=sum(sum(v.values())for v in groups.values())
    assert abs(terminal+decision-total)<1e-8
    ambiguous=sum(sum(v.values())for v in groups.values()if len(v)>1)
    return dict(terminal_before_next_focal_mass=terminal/total,
        next_focal_decision_mass=decision/total,
        first_next_focal_answer_ambiguous_mass=ambiguous/total,
        blind_first_decision_groups=len(groups),
        interpretation='Before another focal choice; public evidence can already infer the answer; ambiguity is not payoff value')


def check_action(sparse,row,ai,args):
    started=time.monotonic();node,offset,actions,children=sparse.expand(row['node'])
    assert [a.to_dict()for a in actions]==row['actions']
    action=row['actions'][ai];assert action['action']=='INVESTIGATE'
    child,global_child,_=children[ai]
    mask=('private',action['player'],action['goal']);focal=row['actor']
    assert mask[1:]not in [tuple(x[:2])for x in row['private_answers']]
    prior=np.zeros(sparse.w);prior[row['world_ids']]=row['posterior']
    tree,roots,mapping,stats=sparse.forest({global_child:prior},focal)
    assert stats['retained_nodes']<=args.max_retained_nodes,stats
    assert tree.entries[next(iter(roots))].node.state.turn_index==row['turn']+1
    values={};lp={};dp_stats={}
    for name,omission in [('full',None),('answer_suppressed',mask)]:
        solved=forest_response(tree,focal,roots,omitted=omission)
        values[name]=sum(float(m@solved['values'][i][:,focal])for i,m in roots.items())
        dp_stats[name]={k:solved[k]for k in ('nodes','cells','sequences','merged_cells','replay_verified')}
        independent=p.sequence_lp(tree,focal,roots,omitted=omission,observations=Observations(tree,focal))
        assert abs(independent['V_omitted_LP']-values[name])<1e-7,(name,independent,values)
        lp[name]=independent
    assert abs(values['full']-row['Q'][ai])<1e-7,(values,row['Q'][ai])
    assert values['answer_suppressed']<=values['full']+1e-7
    chain=first_decision(tree,roots,focal,mask)
    return dict(status='VERIFIED',action_index=ai,action=action,stored_query_Q=row['Q'][ai],
        **values,private_answer_increment=max(0.,values['full']-values['answer_suppressed']),
        independent_full_and_blind_LP_match=True,full_Q_matches=True,
        full_Q_abs_error=abs(values['full']-row['Q'][ai]),
        LP_DP_abs_errors={name:abs(lp[name]['V_omitted_LP']-value)for name,value in values.items()},
        forest_stats=stats,DP=dp_stats,LP=lp,first_next_focal=chain,
        elapsed_seconds=time.monotonic()-started)


def inventory(parent,pool,inventory_root):
    case=inventory_root/'cases'/str(parent['index'])
    summary=json.loads((case/'SUMMARY.json').read_text())
    assert p.m.sha(inventory_root/summary['entries']['path'])==summary['entries']['sha256']
    wanted={}
    with gzip.open(inventory_root/summary['entries']['path'],'rt')as stream:
        for line in stream:
            row=json.loads(line)
            if 'strict_query_pending_answer_causality'in row['tags']:wanted[row['node'],row['cell']]=row
    assert len(wanted)==summary['tags']['strict_query_pending_answer_causality']
    assert p.m.sha(pool/parent['labels']['path'])==parent['labels']['sha256']
    rows=[]
    with gzip.open(pool/parent['labels']['path'],'rt')as stream:
        for line in stream:
            row=json.loads(line)
            if (row['node'],row['cell'])not in wanted:continue
            assert row['counterfactual_mass']>0 and row['query_gap']>p.m.EPS
            rows.append((row,wanted[row['node'],row['cell']]))
    assert len(rows)==len(wanted)
    return rows


def worker(parent,pool,inventory_root,out,args):
    started=time.monotonic();folder=out/'cases'/str(parent['index']);folder.mkdir(parents=True)
    record=dict(index=parent['index'],source_key=parent['source_key'],players=parent['players'],entries=[])
    try:
        assert p.m.sha(p.m.ROOT/parent['admission']['path'])==parent['admission']['sha256']
        source=json.loads((p.m.ROOT/parent['admission']['path']).read_text())['source']
        assert p.digest(source['job']['raw'])==p.digest(parent['raw'])==parent['source_raw_sha256']
        assert p.m.sha(pool/parent['reference']['path'])==parent['reference']['sha256']
        with np.load(pool/parent['reference']['path'])as data:flat=data['probabilities']
        indexed=p.IndexedReference(source['job'],flat);sparse=p.sparse_impl.SparseNative(indexed,args.cache_nodes)
        for row,entry in inventory(parent,pool,inventory_root):
            queries=[i for i,a in enumerate(row['actions'])if a['action']=='INVESTIGATE']
            nonquery=max(row['Q'][i]for i in range(len(row['actions']))if i not in queries)
            full=max(row['Q']);assert abs(full-nonquery-row['query_gap'])<1e-8
            item=dict(entry_id=entry['id'],index=parent['index'],source_key=parent['source_key'],
                node=row['node'],cell=row['cell'],actor=row['actor'],turn=row['turn'],
                own_type=row['own_type'],private_answers=row['private_answers'],
                world_ids=row['world_ids'],posterior=row['posterior'],reference_mass=row['reference_mass'],
                horizon=entry['focal_decisions_to_native_terminal'],physical_skeleton=entry['physical_skeleton'],
                full_entry_value=full,best_nonquery=nonquery,query_gap=row['query_gap'],queries=[])
            for ai in queries:
                try:
                    with timeout(args.action_seconds):result=check_action(sparse,row,ai,args)
                except Exception as exc:
                    result=dict(status='UNAVAILABLE',action_index=ai,action=row['actions'][ai],
                        error=f'{type(exc).__name__}: {exc}',traceback=traceback.format_exc())
                item['queries'].append(result)
            if all(q['status']=='VERIFIED'for q in item['queries']):
                blind=max(q['answer_suppressed']for q in item['queries'])
                assert blind<=full+1e-7
                category=(NO_INCREMENT if full-blind<=p.m.EPS else
                          NECESSARY if blind-nonquery<=p.m.EPS else AMPLIFIES)
                item.update(status='VERIFIED',category=category,best_blind_query=blind,
                    answer_increment_at_best_query=max(0.,full-blind),
                    best_blind_query_minus_nonquery=blind-nonquery,
                    answer_access_policy_gain=full-max(nonquery,blind))
            else:item.update(status='UNAVAILABLE',category=UNKNOWN)
            record['entries'].append(item);p.m.write(folder/'RESULT.json',record)
        record['status']='COMPLETED'
    except Exception as exc:
        record.update(status='ERROR',error=f'{type(exc).__name__}: {exc}',traceback=traceback.format_exc())
    record['elapsed_seconds']=time.monotonic()-started;p.m.write(folder/'RESULT.json',record)
    print(dict(index=parent['index'],source=parent['source_key'],status=record['status'],
               entries=len(record['entries']),seconds=round(record['elapsed_seconds'],2)),flush=True)
    return record


def summarize(results):
    out={}
    for name,cases in [('all',results),('two_player',[r for r in results if r['players']==2]),
                       ('three_player',[r for r in results if r['players']==3])]:
        entries=[e for r in cases for e in r['entries']];queries=[q for e in entries for q in e['queries']]
        categories=Counter(e['category']for e in entries);coverage={}
        for category in [NECESSARY,AMPLIFIES,NO_INCREMENT,UNKNOWN]:
            es=[e for e in entries if e['category']==category]
            coverage[category]=dict(entries=len(es),parents=len({e['index']for e in es}),
                physical_skeletons=len({(e['index'],e['physical_skeleton'])for e in es}),
                guaranteed_multidecision=sum(e['horizon']['min']>=2 for e in es))
        out[name]=dict(parents=len(cases),entries=len(entries),queries=len(queries),
            verified_queries=sum(q['status']=='VERIFIED'for q in queries),categories=dict(categories),
            category_coverage=coverage,parent_errors=[r['index']for r in cases if r['status']!='COMPLETED'],
            unavailable_query_actions=[dict(index=e['index'],node=e['node'],cell=e['cell'],action=q['action'],error=q['error'])
                for e in entries for q in e['queries']if q['status']!='VERIFIED'])
    return out


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--pool',type=Path,required=True)
    parser.add_argument('--inventory',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--indices',default='all');parser.add_argument('--workers',type=int,default=2)
    parser.add_argument('--cache-nodes',type=int,default=8192);parser.add_argument('--max-retained-nodes',type=int,default=250000)
    parser.add_argument('--action-seconds',type=float,default=180.);args=parser.parse_args()
    for key in ('pool','inventory','output'):setattr(args,key,getattr(args,key).resolve())
    pool_complete=json.loads((args.pool/'COMPLETE.json').read_text())
    assert p.m.sha(args.pool/'MANIFEST.json')==pool_complete['manifest_sha256']
    assert p.m.sha(args.pool/'parents.jsonl')==pool_complete['parents_sha256']
    inventory_complete=json.loads((args.inventory/'COMPLETE.json').read_text())
    assert p.m.sha(args.inventory/'PARENTS.json')==inventory_complete['parent_results_sha256']
    parents=[json.loads(x)for x in (args.pool/'parents.jsonl').read_text().splitlines()]
    supply_cases=json.loads((args.inventory/'PARENTS.json').read_text())
    eligible=[x['index']for x in supply_cases if x['tags']['strict_query_pending_answer_causality']]
    selected=eligible if args.indices=='all'else list(map(int,args.indices.split(',')))
    assert set(selected)<=set(eligible)
    p.VERSION,p.REG=VERSION,REG
    p.snapshot(args.output,dict(operation='All legal query targets at strict-query entries; fixed public action, suppress only its private answer',
        workers=args.workers,selected_parent_indices=selected,cache_nodes=args.cache_nodes,
        max_retained_nodes=args.max_retained_nodes,action_seconds=args.action_seconds,
        independent_LP='Every full/blind action,60s perLP,1e-9 feasibility,DP/LP/Q tolerance1e-7',
        answer_mask='Selected target unavailable at every subsequent focal decision; existing entry information/public inference/new public histories retained',
        forced_query='No reoptimization over which query inside a branch; compare all branches afterwards',
        nonquery='Stored best nonquery Q; may include later ordinary investigations in its continuation',
        categories='Needed for strict query advantage; amplifies but blind-query already strictly better; best entry value attainable without current answer; unavailable',
        caveat='Fixed-reference answer-access intervention, not pure public-signal causal attribution or alternate equilibrium; not mainS',
        model_D='NOT_MEASURED',candidate800='NOT_SELECTED'),dict(
            pool=p.ident(args.pool/'MANIFEST.json'),parents=p.ident(args.pool/'parents.jsonl'),
            inventory=p.ident(args.inventory/'PARENTS.json'),inventory_complete=p.ident(args.inventory/'COMPLETE.json')))
    results=[]
    with ProcessPoolExecutor(max_workers=args.workers)as executor:
        pending=[executor.submit(worker,parents[i],args.pool,args.inventory,args.output,args)for i in selected]
        for future in as_completed(pending):
            results.append(future.result());results.sort(key=lambda x:x['index']);p.m.write(args.output/'RESULTS.json',results)
    summary=summarize(results);p.m.write(args.output/'SUMMARY.json',summary)
    p.m.write(args.output/'COMPLETE.json',dict(requested_parents=selected,parents=len(results),
        requested_entries=sum(supply_cases[i]['tags']['strict_query_pending_answer_causality']for i in selected),
        completed_entries=summary['all']['entries'],parent_errors=summary['all']['parent_errors'],
        unavailable_query_actions=len(summary['all']['unavailable_query_actions']),
        results_sha256=p.m.sha(args.output/'RESULTS.json'),summary_sha256=p.m.sha(args.output/'SUMMARY.json'),
        pipeline_snapshot_sha256=p.m.sha(args.output/'pipeline_snapshot.json')))


if __name__=='__main__':main()
