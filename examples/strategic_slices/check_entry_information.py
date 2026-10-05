"""Native public-history VOI before the focal's first decision; same full reference."""
import argparse,json
from collections import defaultdict
from pathlib import Path
import numpy as np
from training.b_sft.social_private_teacher import PrivateInvestigationRules
from training.b_sft.preference_contract import world_weights
from training.strategic_slices.bounded import BoundedPrivateWindow
from training.strategic_slices.common import write_json
from training.strategic_slices.behavior_information import physical_observation,public_history_value
from training.strategic_slices.values import extreme_value


def restore(case,record,path):
    rules=PrivateInvestigationRules(case['raw'])
    tree=BoundedPrivateWindow(rules,rules.initial(),rules.worlds,
        world_weights=world_weights(rules.worlds,case['raw']['background_prior']),
        lookahead_rr=record['full_certificate'].get('lookahead_rr',len(rules.spec.round_robin)),max_nodes=160000,seconds=45)
    with np.load(path,allow_pickle=False) as f:flat=f['probabilities']
    cursor=0
    for i,e in enumerate(tree.entries):
        if e.actor is not None:
            size=len(e.actions)*tree.w;tree.policy[i]=flat[cursor:cursor+size].reshape(len(e.actions),tree.w);cursor+=size
    assert cursor==len(flat);tree.certificate=record['full_certificate']
    assert tree.reference_identity()[0]==tree.certificate['policy_sha256']
    audit=tree.audit_native();assert audit['cutoff_leaves']==0
    return tree


def groups(tree,ego,include_singletons=False):
    reach={0:tree.world_weights.copy()};history={0:[]};pools=defaultdict(dict)
    for i,e in enumerate(tree.entries):
        if i not in reach or e.actor is None:continue
        if e.actor==ego:
            if e.node.pending is None:
                for wi,mass in enumerate(reach[i]):
                    if mass>1e-12:
                        key=physical_observation(tree,i,ego,wi)
                        pools[key].setdefault(i,np.zeros(tree.w))[wi]+=mass
            # Stop at first own response too: cannot erase a previous own observation.
            continue
        for ai,child in enumerate(e.children):
            reach[child]=reach[i]*tree.policy[i][ai];history[child]=history[i]+[e.actions[ai].to_dict()]
    return [(key,masses) for key,masses in pools.items() if include_singletons or len(masses)>1],history


def measure(tree,max_groups=12,include_singletons=False):
    rows=[]
    for ego in range(tree.n):
        pools,histories=groups(tree,ego,include_singletons)
        pools.sort(key=lambda item:-sum(m.sum() for m in item[1].values()))
        for key,masses in pools[:max_groups]:
            inputs=[dict(root_index=i,world_masses=m.tolist()) for i,m in masses.items()]
            for k in (1,2,3):
                value=public_history_value(tree,ego=ego,entries=inputs,k=k,seconds=5)
                detail=[]
                for i,m in masses.items():
                    v=extreme_value(tree,ego,i,m,k)
                    detail.append(dict(index=i,history=histories[i],mass=float(m.sum()),posterior=(m/m.sum()).tolist(),
                        Q=v['root_Q'],actions=[a.to_dict() for a in tree.entries[i].actions]))
                rows.append(dict(ego=ego,k=k,physical_observation=json.loads(key),inputs=inputs,details=detail,**value))
    return rows


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,default=Path('new/local_data/strategic_slices_terminal_reference_consistency_v2'));p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    records=json.loads((a.source/'summary.json').read_text())['results'];results=[]
    for i,r in enumerate(records):
        if r['status']!='verified':continue
        tree=restore(r['case'],r,a.source/f'full_{i}.npz');rows=measure(tree)
        results.append(dict(case=r['case']['name'],worlds=tree.worlds,rows=rows))
        write_json(a.output/'summary.json',dict(results=results))
        print(r['case']['name'],len(rows),'maxS',max((x['S'] for x in rows),default=0),flush=True)

if __name__=='__main__':main()
