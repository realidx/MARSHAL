"""Check the earlier INVESTIGATE on each representative answer-using path."""
import argparse
from collections import Counter
import json
from pathlib import Path
from new import A2H2_structure_20261026 as d

VERSION='A2H2-action-goal-query-path-audit-v3'
REG=d.ROOT/'examples/strategic_slices/versions/A2H2_structure_query_path_v3_20261026/SNAPSHOT.json'


def path_to(indexed,target):
    node=indexed.rules.initial();index=0;path=[]
    while index!=target:
        ni=index+1
        for ai,action in enumerate(indexed.rules.actions(node)):
            child=indexed.rules._apply(node,action);nn,_=indexed.stats(child)
            if ni<=target<ni+nn:
                path.append((index,node,ai,action));node,index=child,ni;break
            ni+=nn
        else:raise AssertionError(target)
    return path


def main():
    p=argparse.ArgumentParser();p.add_argument('--structure',type=Path,default=d.ROOT/'new/A2H2_structure_v1_20261026/audit_frozen_tail_v2')
    p.add_argument('--run',type=Path,default=d.ROOT/'new/three_player_complexity_v1_20261023/local_A2H2_33_v1')
    p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    records=json.load(open(args.structure/'RESULTS.json'));jobs=json.load(open(args.run/'jobs.json'))
    jobs={j['original_index']:j for j in jobs};results={r['original_index']:r for r in json.load(open(args.run/'results.json'))}
    pending={};inputs={}
    for root,name,files in [(args.structure,'structure',['pipeline_snapshot.json','COMPLETE.json','RESULTS.json']),
        (args.run,'run',['pipeline_snapshot.json','COMPLETE.json','jobs.json','results.json'])]:
        for f in files:inputs[f'{name}:{f}']=d.c.identity(root/f)
    for r in records:
        if r['status']!='COMPLETED':continue
        selected=[w for w in r['selected_witnesses']if w['omitted'][0]=='private']
        if not selected:continue
        indexed=d.IndexedReference(jobs[r['original_index']]);queries={}
        for witness in selected:
            chosen=witness['cases'][0]['row'];mask=witness['omitted']
            for ni,node,ai,action in path_to(indexed,chosen['node']):
                a=action.to_dict()
                if indexed.rules.actor(node)==chosen['actor'] and a.get('action')=='INVESTIGATE' and [a['player'],a['goal']]==mask[1:]:
                    key=d.c.stable([ni,chosen['own_type'],a]);queries[key]=dict(node=ni,actor=chosen['actor'],own_type=chosen['own_type'],
                        action_index=ai,action=a,witness_node=chosen['node'],positive_parent=r['positive_contexts']>0,
                        history=[e.to_dict()for e in node.state.transcript],native_actions=[x.to_dict()for x in indexed.rules.actions(node)])
        assert queries
        folder=args.run/Path(results[r['original_index']]['result_path']).parent
        assert d.c.sha(folder/'labels.jsonl.gz')==results[r['original_index']]['labels_sha256']
        inputs[f'{r["original_index"]}:labels']=d.c.identity(folder/'labels.jsonl.gz')
        pending[r['original_index']]=(queries,folder)
    d.c.VERSION,d.c.REG=VERSION,REG
    d.c.snapshot(args.output,dict(operation='Read stored full-terminal Q of earlier own query on representative private-answer paths',
        structure=str(args.structure),run=str(args.run),parents=list(pending),EPS=d.EPS,
        selection='All representative private groups selected by structure v1/v2; same focal/query target ancestor; no new node or parent selection',
        interpretation='Specific INVESTIGATE Q minus best nonquery Q; and regret relative to all current actions',
        scope='Earlier entry Q quoted from hash-verified original terminal labels; no new query Q solve/LP or private acquisition-channel proof',
        game_and_main_Q_S='UNCHANGED',D='NOT_MEASURED',workers=1,threads=1,production='UNCHANGED_V8'),inputs)
    output=[];counts=Counter()
    for original,(queries,folder)in pending.items():
        for row in d.rows_from(folder):
            for query in queries.values():
                if row['node']!=query['node']or row['own_type']!=query['own_type']or row['private_answers']:continue
                assert 'row'not in query and row['actions']==query['native_actions']
                query['row']=row
        for query in queries.values():
            row=query.pop('row');ai=query['action_index'];non=[i for i,a in enumerate(row['actions'])if a.get('action')!='INVESTIGATE']
            gap=row['Q'][ai]-max(row['Q'][i]for i in non);regret=max(row['Q'])-row['Q'][ai]
            status='SUBOPTIMAL'if regret>d.EPS else 'STRICTLY_BETTER_THAN_NONQUERY'if gap>d.EPS else 'TIED_WITH_NONQUERY'
            prefix='positive'if query['positive_parent']else 'zero'
            counts[prefix+':'+status]+=1
            output.append(dict(original_index=original,**query,Q=row['Q'],own_optimal=row['own_optimal'],
                query_Q=row['Q'][ai],best_nonquery_Q=max(row['Q'][i]for i in non),query_minus_best_nonquery=gap,
                regret=regret,status=status,reference_mass=row['reference_mass'],full_query_entry_row=row))
    d.c.write(args.output/'QUERY_PATHS.json',output)
    d.c.write(args.output/'COMPLETE.json',dict(completed=True,parents=len(pending),queries=len(output),counts=counts,
        paths_sha256=d.c.sha(args.output/'QUERY_PATHS.json'),pipeline_snapshot_sha256=d.c.sha(args.output/'pipeline_snapshot.json')))
    print(json.dumps(dict(counts=counts,focus=[r for r in output if r['original_index']in [62,78]]),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
