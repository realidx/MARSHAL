"""Fixed-reference channel diagnostic; never replaces current-node S labels."""
import os
for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[key] = '1'

from collections import defaultdict
import json
from pathlib import Path
import numpy as np

from new.three_player_complexity_v1_20261023.common import ROOT, identity, snapshot, write, sha
from new.three_player_complexity_v1_20261023.worker import tree_for, load
from new.node_qs_audit_v1_20261023.metrics import forest_response, Observations


def main():
    case = ROOT/'new/three_player_complexity_v1_20261023/local_H2_33_v1/cases/11/execution-0000'
    out = ROOT/'new/three_player_complexity_v1_20261023/query35_channel_v1'
    request = json.loads((case/'request.json').read_text())
    examples = json.loads((case/'examples.json').read_text())['query_advantage']
    snapshot(out, dict(operation='Original35 fixed-reference query-answer channel diagnostic',
        source_version='three-player-complexity-study-v1',
        selection='Both positive-query examples exported for original35; not parent-pool selection',
        omission='Suppress this private answer at every subsequent focal decision; public investigation/quota/history retained',
        interpretation='Pre-answer diagnostic only; not current-node S, not an alternate equilibrium',
        tree_config=request['config'], numerical_tolerance=1e-8),
        {name:identity(case/name) for name in ('request.json','reference.npz','examples.json','result.json')} |
        {'diagnostic_script':identity(__file__)})
    tree = tree_for(request['job'], request['config'])
    load(tree, case/'reference.npz')
    tree.deadline = float('inf')
    checks = []
    for row in examples:
        node, focal = row['node'], row['actor']
        ai = next(i for i,a in enumerate(row['actions']) if a['action']=='INVESTIGATE')
        act = row['actions'][ai]; mask = ('private',act['player'],act['goal'])
        prior = np.zeros(tree.w);prior[row['world_ids']] = row['posterior']
        child = tree.entries[node].children[ai]
        values = {}
        for name, omission in (('full',None),('answer_suppressed',mask)):
            solved = forest_response(tree, focal, {child:prior}, omitted=omission)
            values[name] = float(prior @ solved['values'][child][:,focal])
        pass_ai = next(i for i,a in enumerate(row['actions']) if a['action']=='PASS')
        pass_child = tree.entries[node].children[pass_ai]
        solved = forest_response(tree, focal, {pass_child:prior})
        values['pass'] = float(prior @ solved['values'][pass_child][:,focal])
        assert abs(values['full']-row['Q'][ai])<1e-8
        assert abs(values['pass']-row['Q'][pass_ai])<1e-8
        # First next focal decision under the frozen opponents, before any
        # further focal choice; merge using exactly the answer-suppressed key.
        obs = Observations(tree,focal);groups = defaultdict(list);terminal_mass = 0.
        stack = [(child,prior)]
        while stack:
            i,mass = stack.pop();entry = tree.entries[i]
            if entry.actor is None:
                terminal_mass += float(mass.sum());continue
            if entry.actor == focal:
                for wi in np.flatnonzero(mass>0):
                    groups[obs.key(i,int(wi),mask)].append((float(mass[wi]),tree.worlds[wi][act['player']][act['goal']]))
            else:
                for a,ch in enumerate(entry.children):
                    m = mass*tree.policy[i][a]
                    if m.sum()>0:stack.append((ch,m))
        unknown = sum(sum(m for m,_ in members) for members in groups.values()
            if len({v for _,v in members})>1)
        checks.append(dict(node=node,own_type=row['own_type'],query=act,reference_mass=row['reference_mass'],
            **values,private_answer_increment=values['full']-values['answer_suppressed'],
            visible_query_branch_minus_pass=values['answer_suppressed']-values['pass'],
            first_next_focal_decision_blind_groups=len(groups),
            first_next_focal_decision_answer_not_publicly_resolved_mass=unknown,
            terminal_before_next_focal_mass=terminal_mass))
    write(out/'DIAGNOSTIC.json',dict(original_index=35,checks=checks,
        limitation='Frozen opponent responses retained; no invisible-query counterfactual and no equilibrium selection/causal claim.'))
    write(out/'COMPLETE.json',dict(checks=len(checks),all_full_and_pass_Q_replays_match=True,
        diagnostic_sha256=sha(out/'DIAGNOSTIC.json'),pipeline_snapshot_sha256=sha(out/'pipeline_snapshot.json')))
    print(json.dumps(checks,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
