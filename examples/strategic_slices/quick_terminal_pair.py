"""Small horizon diagnostic; first root information cell, k=1..3, 30s per pair.

Run from repository root with PYTHONPATH=. and a directory containing cases.json.
Selection is deliberately restricted to small terminal trees, not representative.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import numpy as np
from training.strategic_slices.bounded import BoundedPrivateWindow
from training.strategic_slices.common import replay_node, write_json, file_hash
from training.strategic_slices.diagnose_bounded import root_entrances
from training.strategic_slices.freeze import source_identity
from training.strategic_slices.values import window_values, masked_answer_value
from training.b_sft.social_private_teacher import PrivateInvestigationRules
from training.b_sft.preference_contract import world_weights


def worker(out, index):
    case=json.loads((out/'cases.json').read_text())[index]
    rules=PrivateInvestigationRules(case['raw']);node=replay_node(rules,case['history'])
    prior=world_weights(rules.worlds,case['raw']['background_prior'])
    report=dict(case=case,players=rules.spec.n_players,worlds=len(rules.worlds),arms={})
    entrance=None
    for arm,depth in [('bounded',1),('terminal',len(rules.spec.round_robin))]:
        started=time.monotonic()
        tree=BoundedPrivateWindow(rules,node,rules.worlds,world_weights=prior,
            lookahead_rr=depth,max_nodes=20000,seconds=12).solve()
        audit=tree.audit_native()
        if arm=='terminal':
            assert all(e.node.state.is_terminal for e in tree.entries if e.actor is None)
        if entrance is None:entrance=root_entrances(tree)[0]
        weights=np.array(entrance['entry_world_weights']);ego=entrance['ego']
        rows=[];previous_c=previous_s=0.
        for k in (1,2,3):
            metric=window_values(tree,ego,0,weights,k);infos=[]
            for ai,action in enumerate(tree.entries[0].actions):
                a=action.to_dict()
                if a.get('action')!='INVESTIGATE':continue
                slot=(a['player'],a['goal'])
                support={w[slot[0]][slot[1]] for w,m in zip(tree.worlds,weights) if m>0}
                if len(support)>1:
                    v=masked_answer_value(tree,ego=ego,root_index=0,root_weights=weights,query_slot=slot,k=k)
                    s=v['S'];conditional=max(0.,v['full']['root_action_values'][ai]-v['masked']['root_action_values'][ai])
                else:s=conditional=0.
                infos.append(dict(slot=slot,S=s,S_given_query=conditional))
            s=max((q['S'] for q in infos),default=0.)
            c=metric['C_span'];inc=c-previous_c;previous_c=c
            selected=c>.1 and (k==1 or inc>.05 or s-previous_s>.05)
            if c>.1:previous_s=s
            q=np.asarray(metric['root_Q'])
            rows.append(dict(k=k,**metric,S_max=s,information_values=infos,
                selected_before_parent_cap=selected,best_actions=np.flatnonzero(q>=q.max()-1e-8).tolist()))
        report['arms'][arm]=dict(cutoff=tree.cutoff,nodes=len(tree.entries),
            certificate=tree.certificate,native_audit=audit,rows=rows,
            actions=[a.to_dict() for a in tree.entries[0].actions],seconds=time.monotonic()-started)
        report['entrance']=entrance
        write_json(out/f'partial_{index}.json',report)
    assert report['arms']['bounded']['actions']==report['arms']['terminal']['actions']
    assert report['arms']['bounded']['cutoff']<report['arms']['terminal']['cutoff']
    report['status']='paired-certified'
    write_json(out/f'result_{index}.json',report)


def main():
    cli=argparse.ArgumentParser(description=__doc__);cli.add_argument('--output',type=Path,required=True)
    cli.add_argument('--worker',type=int);args=cli.parse_args();out=args.output.resolve()
    if args.worker is not None:worker(out,args.worker);return
    sources=source_identity();start=time.monotonic()
    cases=json.loads((out/'cases.json').read_text())
    def run(index):
        env=dict(os.environ,OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1')
        with (out/f'worker_{index}.log').open('w') as log:
            try:
                p=subprocess.run([sys.executable,__file__,'--output',str(out),'--worker',str(index)],
                    stdout=log,stderr=subprocess.STDOUT,env=env,timeout=30)
                status='failed' if p.returncode else 'paired-certified'
            except subprocess.TimeoutExpired:status='timeout'
        path=out/f'result_{index}.json'
        return json.loads(path.read_text()) if status=='paired-certified' else dict(case=cases[index],status=status)
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,range(len(cases))))
    report=dict(scope='Convenience sample of small trees; no population difference-rate claim. Same solver, full terminal leaves versus current bounded horizon; references re-solved separately.',
        per_pair_wall_cap_seconds=30,k=[1,2,3],information_cell='First deterministic root information cell per entrance',
        seconds=time.monotonic()-start,cases_sha256=file_hash(out/'cases.json'),
        script_sha256=file_hash(__file__),source_sha256=sources,source_unchanged=sources==source_identity(),results=results)
    write_json(out/'summary.json',report)
    print([(r['case']['name'],r['status']) for r in results],flush=True)


if __name__=='__main__':main()
