"""Remeasure saved terminal references; never re-solve or replace frozen labels."""
import argparse,json,os,subprocess,sys,time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import numpy as np
from training.b_sft.social_private_teacher import PrivateInvestigationRules
from training.b_sft.preference_contract import world_weights
from training.strategic_slices.bounded import BoundedPrivateWindow
from training.strategic_slices.common import replay_node,write_json,file_hash
from training.strategic_slices.diagnose_bounded import root_entrances
from training.strategic_slices.behavior_information import public_behavior_value


def worker(source,out,index):
    case=json.loads((source/'cases.json').read_text())[index]
    saved=json.loads((source/f'result_{index}.json').read_text())
    rules=PrivateInvestigationRules(case['raw'])
    tree=BoundedPrivateWindow(rules,replay_node(rules,case['history']),rules.worlds,
        world_weights=world_weights(rules.worlds,case['raw']['background_prior']),
        lookahead_rr=len(rules.spec.round_robin),max_nodes=15000,seconds=30)
    path=source/f'reference_{index}.npz'
    with np.load(path,allow_pickle=False) as data:flat=data['probabilities']
    cursor=0
    for i,e in enumerate(tree.entries):
        if e.actor is not None:
            size=len(e.actions)*tree.w;tree.policy[i]=flat[cursor:cursor+size].reshape(len(e.actions),tree.w);cursor+=size
    assert cursor==len(flat)
    tree.certificate=saved['certificate']
    assert tree.reference_identity()[0]==tree.certificate['policy_sha256']
    audit=tree.audit_native();assert audit['cutoff_leaves']==0
    rows=[]
    for entrance in root_entrances(tree)[:2]:
        for k in (2,3):
            result=public_behavior_value(tree,ego=entrance['ego'],root_index=0,root_weights=entrance['entry_world_weights'],k=k)
            rows.append(dict(entrance=entrance,k=k,**result))
    write_json(out/f'result_{index}.json',dict(status='verified',index=index,parent_id=case['parent_id'],
        source_reference_sha256=file_hash(path),certificate_policy_identity_verified=True,audit=audit,rows=rows))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,default=Path('new/local_data/strategic_slices_terminal_entry_fresh_v1'));p.add_argument('--output',type=Path,required=True);p.add_argument('--worker',type=int)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    if a.worker is not None:worker(a.source,a.output,a.worker);return
    records=json.loads((a.source/'summary.json').read_text())['results'];chosen={}
    for i,r in enumerate(records):
        if r['status']!='certified' or r['case']['remaining']<2:continue
        c=r['case'];key=(-c['remaining'],c['nodes'],i)
        if c['parent_id'] not in chosen or key<chosen[c['parent_id']][0]:chosen[c['parent_id']]=(key,i)
    indices=[x[1] for x in chosen.values()];start=time.monotonic()
    def launch(i):
        with (a.output/f'worker_{i}.log').open('w') as log:
            try:
                r=subprocess.run([sys.executable,__file__,'--source',str(a.source),'--output',str(a.output),'--worker',str(i)],stdout=log,stderr=subprocess.STDOUT,timeout=30,env=dict(os.environ,OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1'))
                status='failed' if r.returncode else 'verified'
            except subprocess.TimeoutExpired:status='timeout'
        return json.loads((a.output/f'result_{i}.json').read_text()) if status=='verified' else dict(index=i,status=status,oracle_label=None)
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(launch,indices))
    rows=[row for r in results if r['status']=='verified' for row in r['rows']]
    summary=dict(scope='One saved certified entrance per fresh parent, prefer three remaining proposals then smallest tree; first two root cells, k=2/3. Convenience diagnostic, not coverage or frequency estimate.',
        seconds=time.monotonic()-start,attempted=len(indices),verified=sum(r['status']=='verified' for r in results),
        comparisons=len(rows),positive_S_behavior=sum(r['S']>.05 for r in rows),max_S_behavior=max((r['S'] for r in rows),default=None),
        comparisons_with_merged_cells=sum(r['merged_information_cells']>0 for r in rows),results=results)
    write_json(a.output/'summary.json',summary);print({k:v for k,v in summary.items() if k!='results'})

if __name__=='__main__':main()
