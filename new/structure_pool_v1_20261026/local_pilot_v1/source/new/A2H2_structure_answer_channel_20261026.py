"""Separate private answer access from the unchanged public query branch."""
import argparse
import json
from pathlib import Path
import numpy as np
from new import A2H2_structure_20261026 as d
from new.node_qs_audit_v1_20261023.metrics import forest_response

VERSION='A2H2-structure-answer-channel-audit-v4'
REG=d.ROOT/'examples/strategic_slices/versions/A2H2_structure_answer_channel_v4_20261026/SNAPSHOT.json'


def main():
    p=argparse.ArgumentParser();p.add_argument('--queries',type=Path,default=d.ROOT/'new/A2H2_structure_v1_20261026/query_paths_v3')
    p.add_argument('--run',type=Path,default=d.ROOT/'new/three_player_complexity_v1_20261023/local_A2H2_33_v1')
    p.add_argument('--output',type=Path,required=True);p.add_argument('--max-nodes',type=int,default=200000)
    p.add_argument('--construct-seconds',type=float,default=30.);args=p.parse_args()
    selected=[r for r in json.load(open(args.queries/'QUERY_PATHS.json'))if r['original_index']in [62,78]]
    assert {r['original_index']for r in selected}=={62,78} and len(selected)==2
    jobs={j['original_index']:j for j in json.load(open(args.run/'jobs.json'))}
    results={r['original_index']:r for r in json.load(open(args.run/'results.json'))}
    inputs={}
    for root,files in [(args.queries,['pipeline_snapshot.json','COMPLETE.json','QUERY_PATHS.json']),(args.run,['jobs.json','results.json','pipeline_snapshot.json'])]:
        for f in files:inputs[str(root/f)]=d.c.identity(root/f)
    for r in selected:
        rr=results[r['original_index']];ref=args.run/rr['reference_path'];assert d.c.sha(ref)==rr['reference_sha256']
        inputs[str(ref)]=d.c.identity(ref)
    d.c.VERSION,d.c.REG=VERSION,REG
    d.c.snapshot(args.output,dict(operation='Representative62/78 query answer-channel diagnosis against the same frozen opponents',
        queries=str(args.queries),run=str(args.run),selected_original_indices=[62,78],max_nodes=args.max_nodes,
        construct_seconds=args.construct_seconds,EPS=d.EPS,
        suppression='Chosen target answer unavailable at all future focal decisions; public query/history/quota and opponent policies unchanged',
        objective='Exact complete focal strategy to native terminal in the recovered remaining subtree; full versus answer-suppressed forest',
        comparison='Full value must match stored specific-query Q; best nonquery quoted from same stored entry Q',
        caveat='Pre-answer channel diagnostic, not main current-node S; not an invisible-query or alternate-equilibrium experiment',
        D='NOT_MEASURED',production='UNCHANGED_V8',workers=1,threads=1),inputs)
    output=[]
    for selected_row in selected:
        original=selected_row['original_index'];rr=results[original]
        with np.load(args.run/rr['reference_path'])as data:flat=data['probabilities']
        indexed=d.IndexedReference(jobs[original],flat);row=selected_row['full_query_entry_row']
        node,offset=indexed.find(row['node']);ids=[w for w,m in zip(row['world_ids'],row['posterior'])if m>0]
        prior=np.array([m for m in row['posterior']if m>0]);tree=d.BoundedPrivateWindow(indexed.rules,node,
            [indexed.rules.worlds[i]for i in ids],world_weights=prior,lookahead_rr=3,max_nodes=args.max_nodes,seconds=args.construct_seconds)
        assert not tree.cutoff_leaves
        pos=offset
        for entry,policy in zip(tree.entries,tree.policy):
            if policy is None:continue
            size=len(entry.actions)*indexed.w;policy[:]=flat[pos:pos+size].reshape(len(entry.actions),indexed.w)[:,ids];pos+=size
        assert pos-offset==indexed.stats(node)[1]
        assert [a.to_dict()for a in tree.entries[0].actions]==row['actions']
        ai=selected_row['action_index'];child=tree.entries[0].children[ai];focal=row['actor'];tree.deadline=float('inf')
        mask=('private',selected_row['action']['player'],selected_row['action']['goal']);values={}
        for name,omitted in [('full',None),('answer_suppressed',mask)]:
            solved=forest_response(tree,focal,{child:prior},omitted=omitted)
            values[name]=float(prior@solved['values'][child][:,focal])
        assert abs(values['full']-selected_row['query_Q'])<1e-7
        assert values['full']>=values['answer_suppressed']-1e-7
        output.append(dict(original_index=original,node=row['node'],query=selected_row['action'],
            native_subtree_nodes=len(tree.entries),**values,best_nonquery=selected_row['best_nonquery_Q'],
            private_answer_increment=values['full']-values['answer_suppressed'],
            no_answer_query_minus_best_nonquery=values['answer_suppressed']-selected_row['best_nonquery_Q'],
            full_query_minus_best_nonquery=values['full']-selected_row['best_nonquery_Q'],
            full_Q_replay_matches=True))
    d.c.write(args.output/'CHANNELS.json',output)
    d.c.write(args.output/'COMPLETE.json',dict(completed=True,cases=2,all_full_Q_replays_match=True,
        channels_sha256=d.c.sha(args.output/'CHANNELS.json'),pipeline_snapshot_sha256=d.c.sha(args.output/'pipeline_snapshot.json')))
    print(json.dumps(output,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
