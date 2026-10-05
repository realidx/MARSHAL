"""Declared sensitivity panel: 4 priors x linear/binary, one calibrated mechanism."""
import argparse,json,os,subprocess,sys,time
from copy import deepcopy
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from examples.strategic_slices.check_entry_information import measure
from training.b_sft.social_private_teacher import PrivateInvestigationRules
from training.b_sft.preference_contract import profile,world_weights
from training.strategic_slices.bounded import BoundedPrivateWindow
from training.strategic_slices.common import write_json,save_reference

def worker(out,i,mixed=False):
    raw=deepcopy(json.loads(Path('examples/strategic_slices/fixtures/public_history_information.json').read_text())['raw'])
    prior='balanced' if mixed else ('balanced','want_heavy','neutral_heavy','avoid_heavy')[i%4]
    mask=i+1 if mixed else (7 if i>=4 else 0)
    raw['background_prior']=profile(prior)
    for g in raw['game']['goals']:g['binary']=bool(mask & (1<<g['goal_id']))
    write_json(out/f'raw_{i}.json',raw);rules=PrivateInvestigationRules(raw);start=time.monotonic()
    tree=BoundedPrivateWindow(rules,rules.initial(),rules.worlds,world_weights=world_weights(rules.worlds,raw['background_prior']),lookahead_rr=3,max_nodes=30000,seconds=10).solve()
    audit=tree.audit_native();assert audit['cutoff_leaves']==0
    save_reference(out/f'reference_{i}.npz',tree)
    rows=measure(tree,max_groups=6,include_singletons=True)
    write_json(out/f'result_{i}.json',dict(status='verified',index=i,seed=None,players=3,
        origin=dict(kind='public-history-calibration-variant',base_seed=2026100609,prior=prior,scoring_mask=mask),
        worlds=tree.worlds,certificate=tree.certificate,audit=audit,seconds=time.monotonic()-start,rows=rows))

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--worker',type=int)
    p.add_argument('--mixed',action='store_true',help='Six mixed linear/binary masks under balanced prior')
    a=p.parse_args();out=a.output;out.mkdir(parents=True,exist_ok=True)
    if a.worker is not None:worker(out,a.worker,a.mixed);return
    start=time.monotonic()
    def launch(i):
        with (out/f'worker_{i}.log').open('w') as log:
            try:
                command=[sys.executable,__file__,'--output',str(out),'--worker',str(i)]
                if a.mixed:command.append('--mixed')
                r=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=30,env=dict(os.environ,OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1'))
                status='failed' if r.returncode else 'done'
            except subprocess.TimeoutExpired:status='hard_timeout'
        if status=='done':return json.loads((out/f'result_{i}.json').read_text())
        if 'wall budget exceeded' in (out/f'worker_{i}.log').read_text():status='solver_time_budget'
        return dict(status=status,index=i,oracle_label=None)
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(launch,range(6 if a.mixed else 8)))
    rows=[r for c in results if c['status']=='verified' for r in c['rows']]
    write_json(out/'summary.json',dict(scope=('Same calibrated mechanism, six mixed scoring masks under balanced prior.' if a.mixed else 'Same calibrated mechanism, four priors and two scoring modes.')+' Not independent random discoveries. Ten seconds per solve versus six in random search.',seconds=time.monotonic()-start,results=results,comparisons=len(rows),positive_S=sum(r['S']>.05 for r in rows),max_S=max((r['S'] for r in rows),default=0)))
    print([(r['index'],r['status'],max((x['S'] for x in r.get('rows',[])),default=0)) for r in results],flush=True)

if __name__=='__main__':main()
