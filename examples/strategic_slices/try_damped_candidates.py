"""Diagnostic damped-BR candidate search, with unchanged full certification."""
import argparse
import json
from pathlib import Path
import time
import numpy as np
from training.b_sft.preference_contract import world_weights
from training.b_sft.social_private_teacher import PrivateInvestigationRules
from training.b_sft.shared_teacher import SearchLimit
from training.strategic_slices.bounded import BoundedPrivateWindow
from training.strategic_slices.batched_response import BatchedResponse
from training.strategic_slices.common import write_json, save_reference, file_hash
import training.strategic_slices.equilibrium as eq


def search(tree, **kwargs):
    batch=BatchedResponse(tree);started=time.monotonic();attempts=0
    for rate in (.5, .25, .75):
        for i,e in enumerate(tree.entries):
            if e.actor is not None:tree.policy[i][:]=1/len(e.actions)
        for step in range(80):
            tree._check()
            for player in range(tree.n):
                updates,_=batch.response(player)
                for i,p in updates.items():tree.policy[i][:]=(1-rate)*tree.policy[i]+rate*p
            if step%4!=3:continue
            original=eq._copy(tree.policy)
            for threshold in (1e-10,1e-6,1e-3):
                for i,p in enumerate(original):
                    if p is None:continue
                    candidate=p.copy();candidate[candidate<threshold]=0
                    candidate/=candidate.sum(axis=0,keepdims=True)
                    tree.policy[i]=candidate
                attempts+=1
                if not batch.locally_admissible():continue
                accepted=eq.certify_policy(tree)
                if accepted is not None:
                    accepted['certificate'].update(candidate_method='diagnostic-damped-ordered-BR',
                        damping=rate,steps=step+1,candidate_probability_snap=threshold,
                        independent_final_certification=True,candidate_attempts=attempts)
                    return accepted
            tree.policy=original
    raise SearchLimit('Damped BR candidates did not pass complete deviation/tie checks')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--raw',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--seconds',type=int,default=120)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    r=dict(raw=str(a.raw),raw_sha256=file_hash(a.raw),status='started',budget=a.seconds)
    write_json(a.output/'result.json',r);began=time.monotonic();original=eq.solve_equilibrium
    try:
        raw=json.loads(a.raw.read_text());rules=PrivateInvestigationRules(raw)
        tree=BoundedPrivateWindow(rules,rules.initial(),rules.worlds,
            world_weights=world_weights(rules.worlds,raw['background_prior']),lookahead_rr=3,max_nodes=160000,seconds=a.seconds)
        r['construction_seconds']=time.monotonic()-began;r['nodes']=len(tree.entries);r['worlds']=tree.w
        eq.solve_equilibrium=search
        tree.solve();r.update(status='certified',certificate=tree.certificate)
        tree.deadline=time.monotonic()+120;r['native_audit']=tree.audit_native()
        save_reference(a.output/'reference.npz',tree)
    except Exception as exc:r.update(status='failed',reason=str(exc))
    finally:
        eq.solve_equilibrium=original;r['seconds']=time.monotonic()-began
        write_json(a.output/'result.json',r)
    print(r['status'],r['seconds'],r.get('reason'),flush=True)


if __name__=='__main__':main()
