"""Bounded-budget search for native terminal-equilibrium entry-history information."""
import argparse,json,os,subprocess,sys,time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from examples.strategic_slices.check_entry_information import measure
from training.strategic_slices.build import sample_parent
from training.strategic_slices.bounded import BoundedPrivateWindow
from training.strategic_slices.common import save_reference,write_json
from training.strategic_slices.diagnose_bounded import count_bounded_nodes
from training.b_sft.social_private_teacher import PrivateInvestigationRules
from training.b_sft.preference_contract import world_weights

def worker(out,i):
    config=json.loads((out/'config.json').read_text())
    seed=config['start_seed']+i;players=2 if i<config['two_player_count'] else 3
    raw=sample_parent(seed,players,rounds=1);write_json(out/f'raw_{i}.json',raw)
    rules=PrivateInvestigationRules(raw);start=time.monotonic()
    nodes=count_bounded_nodes(rules,rules.initial(),3)['unfolded_public_history_nodes']
    if nodes>30000:write_json(out/f'result_{i}.json',dict(status='node_budget',index=i,nodes=nodes));return
    tree=BoundedPrivateWindow(rules,rules.initial(),rules.worlds,world_weights=world_weights(rules.worlds,raw['background_prior']),lookahead_rr=3,max_nodes=30000,seconds=6).solve()
    audit=tree.audit_native();assert audit['cutoff_leaves']==0
    save_reference(out/f'reference_{i}.npz',tree)
    rows=measure(tree,max_groups=6,include_singletons=config['include_singletons'])
    write_json(out/f'result_{i}.json',dict(status='verified',index=i,seed=seed,players=players,nodes=nodes,worlds=tree.worlds,certificate=tree.certificate,audit=audit,seconds=time.monotonic()-start,rows=rows))

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--worker',type=int)
    p.add_argument('--start-seed',type=int,default=2026100600);p.add_argument('--count',type=int,default=12)
    p.add_argument('--two-player-count',type=int,default=0);p.add_argument('--include-singletons',action='store_true')
    a=p.parse_args();out=a.output;out.mkdir(parents=True,exist_ok=True)
    if a.worker is not None:worker(out,a.worker);return
    if a.count<1 or not 0<=a.two_player_count<=a.count:raise ValueError('Invalid parent counts')
    write_json(out/'config.json',dict(start_seed=a.start_seed,count=a.count,two_player_count=a.two_player_count,include_singletons=a.include_singletons))
    start=time.monotonic()
    def launch(i):
        with (out/f'worker_{i}.log').open('w') as log:
            try:
                r=subprocess.run([sys.executable,__file__,'--output',str(out),'--worker',str(i)],stdout=log,stderr=subprocess.STDOUT,timeout=25,env=dict(os.environ,OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1'))
                status='failed' if r.returncode else 'done'
            except subprocess.TimeoutExpired:status='hard_timeout'
        if status=='done':return json.loads((out/f'result_{i}.json').read_text())
        log=(out/f'worker_{i}.log').read_text()
        if 'wall budget exceeded' in log:status='solver_time_budget'
        elif 'candidate information-cell budget exceeded' in log:status='joint_cell_budget'
        elif 'did not pass complete deviation/tie checks' in log:status='uncertified_reference'
        return dict(status=status,index=i,oracle_label=None)
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(launch,range(a.count)))
    rows=[r for c in results if c['status']=='verified' for r in c['rows']]
    summary=dict(config=json.loads((out/'config.json').read_text()),seconds=time.monotonic()-start,results=results,comparisons=len(rows),positive_S=sum(r['S']>.05 for r in rows),max_S=max((r['S'] for r in rows),default=0))
    write_json(out/'summary.json',summary)
    print([(r['index'],r['status'],max((x['S'] for x in r.get('rows',[])),default=0)) for r in results],flush=True)

if __name__=='__main__':main()
