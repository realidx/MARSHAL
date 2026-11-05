"""LP validation of own-S witnesses, including current proposal witnesses."""
import argparse
from collections import defaultdict
import gzip
import json
from pathlib import Path
import time

import numpy as np

from new.three_player_complexity_v1_20261023 import common as c
from new.three_player_complexity_v1_20261023.worker import tree_for, load
from new.node_qs_audit_v1_20261023.metrics import Observations
from new.node_qs_audit_v1_20261023.witness import sequence_lp
from training.strategic_slices.equilibrium import _reach

VERSION = 'A2H2-own-S-witness-LP-v2'
REG = c.ROOT/'examples/strategic_slices/versions/A2H2_witness_LP_v2_20261025/SNAPSHOT.json'
EPS = 1e-8


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    results = json.loads((args.run/'results.json').read_text())
    inputs = {name:c.identity(args.run/name) for name in ('pipeline_snapshot.json','COMPLETE.json','results.json','jobs.json')}
    selected = []
    for result in results:
        if result.get('labels') != 'MEASURED':
            continue
        counts = result['summary']['counterfactual']
        if not (counts['private_S_positive'] or counts['history_S_positive']):
            continue
        folder = args.run/Path(result['result_path']).parent
        for name, digest in [('reference.npz',result['reference_sha256']),('labels.jsonl.gz',result['labels_sha256'])]:
            assert c.sha(folder/name) == digest
            inputs[f'{result["index"]}:{name}'] = c.identity(folder/name)
        inputs[f'{result["index"]}:request'] = c.identity(folder/'request.json')
        selected.append((result, folder))
    c.VERSION, c.REG = VERSION, REG
    c.snapshot(args.output, dict(operation='Independent own-S LP checks on A2H2 witnesses',
        run=str(args.run), numeric_epsilon=EPS, indices=[r['index'] for r,_ in selected],
        admission='All measured parents with any positive own S; skip constructing zero-S trees only for this witness check',
        witness_selection='Per game/channel: largest S overall and largest proposal S; deterministic score, reference mass, earliest node; deduplicate',
        optimization='No game/profile/label changes; only avoid needless tree construction on no-witness parents',
        LP='Check full-information and omitted-forest aggregate own optimum; bound individual true-context own value across omitted own optima',
        social='LP relaxes response-secondary constraints for conservative individual S bounds',
        verification_scope='Selected witnesses only, not every positive label or across-reference invariance',
        workers=1,other_resources='Tree construction uses actual saved request config; no additional hard per-LP limit; macOS memory limit not applied'),inputs)
    checks = []
    for result, folder in selected:
        started = time.monotonic()
        with gzip.open(folder/'labels.jsonl.gz','rt') as stream:
            rows = list(map(json.loads,stream))
        candidates = {}
        for channel in ('private','history'):
            for proposal_only in (False,True):
                possible = [(item['S'],row,item) for row in rows for item in row['S_items']
                    if item['omitted'][0] == channel and item['S'] > EPS
                    and (not proposal_only or row['phase']=='proposal')]
                if not possible:
                    continue
                _, row, item = max(possible,key=lambda x:(x[0],x[1]['reference_mass'],-x[1]['node'],-x[1]['cell']))
                key = (row['node'],row['cell'],tuple(item['omitted']))
                if key not in candidates:
                    candidates[key] = (row,item,[])
                candidates[key][2].append(channel+('_proposal' if proposal_only else '_all'))
        assert candidates
        request = json.loads((folder/'request.json').read_text())
        tree = tree_for(request['job'],request['config'])
        load(tree,folder/'reference.npz');tree.deadline=float('inf')
        cached = {}
        for chosen,item,categories in candidates.values():
            focal=chosen['actor'];mask=tuple(item['omitted'])
            if focal not in cached:
                cached[focal]=(Observations(tree,focal),_reach(tree,focal))
            obs,reach=cached[focal]
            key=obs.key(chosen['node'],chosen['world_ids'][0],mask)
            members=[row for row in rows if row['actor']==focal and
                any(tuple(x['omitted'])==mask for x in row['S_items']) and
                obs.key(row['node'],row['world_ids'][0],mask)==key]
            roots={}
            for row in members:
                roots.setdefault(row['node'],np.zeros(tree.w))[row['world_ids']]=reach[row['node']][row['world_ids']]
            lp=sequence_lp(tree,focal,roots,omitted=mask,observations=obs,
                target=(chosen['node'],set(chosen['world_ids'])))
            full_lp=sequence_lp(tree,focal,roots,omitted=None,observations=obs)
            total=sum(m.sum() for m in roots.values())
            omitted_mean=sum(row['counterfactual_mass']*next(x['V_omitted'] for x in row['S_items']
                if tuple(x['omitted'])==mask) for row in members)/total
            full_mean=sum(row['counterfactual_mass']*max(row['Q']) for row in members)/total
            assert abs(lp['V_omitted_LP']-omitted_mean)<1e-7
            assert abs(full_lp['V_omitted_LP']-full_mean)<1e-7
            full=max(chosen['Q']);lower=max(0.,full-lp['target_own_value_max']);upper=max(0.,full-lp['target_own_value_min'])
            assert lower-1e-7<=item['S']<=upper+1e-7
            entry = dict(original_index=result['original_index'],index=result['index'],
                node=chosen['node'],cell=chosen['cell'],actor=focal,phase=chosen['phase'],turn=chosen['turn'],
                categories=categories,omitted=list(mask),S=item['S'],entry_action_regret=item['entry_action_regret'],
                reference_mass=chosen['reference_mass'],S_conservative_interval=[lower,upper],
                full_forest_mean=full_mean,omitted_forest_mean=omitted_mean,
                forest_information_gain=full_mean-omitted_mean,full_LP_matches=True,omitted_LP_matches=True,**lp)
            checks.append(entry)
        c.write(args.output/'CHECKS.json',checks)
        print(dict(original_index=result['original_index'],witnesses=len(candidates),
                   elapsed=round(time.monotonic()-started,2)),flush=True)
    c.write(args.output/'COMPLETE.json',dict(parents=len(selected),witnesses=len(checks),
        full_and_omitted_LP_checks=2*len(checks),all_LP_checks_matched=True,
        positive_conservative_lower_bounds=sum(x['S_conservative_interval'][0]>EPS for x in checks),
        checks_sha256=c.sha(args.output/'CHECKS.json'),pipeline_snapshot_sha256=c.sha(args.output/'pipeline_snapshot.json')))


if __name__=='__main__':
    main()
