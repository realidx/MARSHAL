"""Frozen, outcome-blind three-player structural coverage pilot; never production."""
import os
THREAD_KEYS=('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS')
for key in THREAD_KEYS:os.environ[key]='1'

import argparse
from collections import Counter
from hashlib import sha256
from itertools import combinations,product
import json
from pathlib import Path
import platform
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'third_party/negotiation_benchmark/src')]
import numpy as np
import scipy
from new.strategic_game_v1_20261021.rules import StrategicRules
from new.game_design_feasibility_20261021.design import count_public_tree
from training.b_sft.preference_contract import profile,world_weights
from training.strategic_slices.oracle_consistent import canonical_parent
from new.three_player_complexity_v1_20261023 import remote

VERSION='three-player-structure-coverage-pilot-v1'
REG=ROOT/'examples/strategic_slices/versions/structure_pool_v1_20261026/SNAPSHOT.json'


def stable(x):return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False)
def sha(p):return sha256(Path(p).read_bytes()).hexdigest()
def write(p,x):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')


def snapshot(out,config,inputs=None):
    meta=json.loads(REG.read_text());assert meta['version']==VERSION
    for p,h in meta['source_hashes'].items():assert sha(ROOT/p)==h,p
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    for p in meta['source_hashes']:
        dest=out/'source'/p;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/p,dest)
    shutil.copyfile(REG,out/'registered_snapshot_at_start.json')
    write(out/'pipeline_snapshot.json',dict(version=VERSION,actual_argv=sys.argv,
        resolved_config=config,source_hashes=meta['source_hashes'],registration_sha256=sha(REG),
        inputs=inputs or {},parent_contract=meta['parent_contract'],
        environment=dict(python=sys.version,executable=sys.executable,numpy=np.__version__,scipy=scipy.__version__,
            platform=platform.platform(),threads={k:os.environ.get(k,'NOT_RECORDED')for k in THREAD_KEYS},
            initialized_numeric_threadpools='NOT_MEASURED'),
        model='NOT_USED',prompt_tools='NOT_CHANGED_NOT_USED',D='NOT_MEASURED',
        training_reward_advantage='NOT_CHANGED_NOT_USED',production_active='terminal-node-regret-grpo-readable-v8'))


def generate_pair(pair,goals,geometry,scoring):
    seed=202610260000+pair
    top,mode,mask,public,order=[np.random.default_rng(s)for s in np.random.SeedSequence(seed).spawn(5)]
    counts=[1,1,1];dual=int(top.integers(3));counts[dual]=2
    refs=[(p,a)for p,n in enumerate(counts)for a in range(n)]
    possible=[x for n in (2,3)for x in combinations(refs,n)if len({p for p,a in x})>=2]
    # Enumerate small geometry universe only, not game histories or payoffs.
    eligible=[]
    for edges in combinations(possible,goals):
        if set().union(*map(set,edges))!=set(refs):continue
        bundled=any((dual,0)in e and (dual,1)in e for e in edges)
        signatures=[tuple(i for i,e in enumerate(edges)if (dual,a)in e)for a in (0,1)]
        if geometry=='split' and (bundled or signatures[0]==signatures[1]):continue
        if geometry=='bundled' and not bundled:continue
        eligible.append(edges)
    assert eligible
    chosen=eligible[int(top.integers(len(eligible)))];chosen=[chosen[int(i)]for i in top.permutation(goals)]
    if scoring=='binary':binary=[True]*goals
    elif scoring=='linear':binary=[False]*goals
    else:
        patterns=[x for x in product((False,True),repeat=goals)if any(x)and not all(x)]
        binary=list(patterns[int(mode.integers(len(patterns)))])
    goal_rows=[dict(goal_id=g,binary=b,required_actions=[dict(player_id=p,action_id=a)for p,a in e])
        for g,(e,b)in enumerate(zip(chosen,binary))]
    cells=[(p,g)for p in range(3)for g in range(goals)]
    random_masks=[x for x in combinations(cells,2)if x[0][0]!=x[1][0]]
    # Hidden cells share a goal and both owners supply a required commitment.
    # Admission never sees their preference values or any utility/Q/S/model output.
    targeted_masks=sorted({tuple(sorted(((p,g),(q,g))))for g,e in enumerate(chosen)
        for p,q in combinations(sorted({p for p,a in e}),2)})
    random_mask=random_masks[int(mask.integers(len(random_masks)))]
    target_mask=targeted_masks[int(mask.integers(len(targeted_masks)))]
    fixed=public.choice([1,0,-1],size=(3,goals));rotation=list(map(int,order.permutation(3)))
    output=[]
    for arm,masked in [('uniform_mask',random_mask),('shared_goal_mask',target_mask)]:
        catalogues={}
        for p in range(3):
            slots=[g for pp,g in masked if pp==p];rows=[]
            for values in product((1,0,-1),repeat=len(slots)):
                row=fixed[p].tolist()
                for g,v in zip(slots,values):row[g]=v
                rows.append(row)
            catalogues[str(p)]=rows
        raw=dict(game=dict(n_players=3,n_actions_per_player=counts,goals=goal_rows,round_robin=rotation*2,
            max_changes=1,menu_enabled=False,investigation_budget=1,offer_budget=1),ego=0,
            own_preferences=catalogues['0'][0],type_catalogues=catalogues,
            background_prior=profile('balanced'),history=[])
        output.append(dict(index=2*pair+len(output),id=sha256(stable(raw).encode()).hexdigest()[:24],
            pair_id=pair,arm=arm,original_index=None,kind='new_structural_pilot_parent',raw=raw,
            canonical_id=canonical_parent(raw),seed=seed,
            configuration=dict(players=3,rounds=2,goals=goals,geometry=geometry,scoring=scoring),
            origin=dict(hidden_cells=list(map(list,masked)),public_preference_draw=fixed.tolist(),
                eligible_geometries=len(eligible),dual_player=dual,old_pool_member=False),
            oracle_status='NOT_ATTEMPTED',Q_S_D_status='NOT_MEASURED'))
    return output


def validate(rows):
    assert len(rows)==24 and [r['index']for r in rows]==list(range(24))
    for row in rows:
        raw=row['raw'];rules=StrategicRules(raw)
        assert len(rules.worlds)==9
        weights=world_weights(rules.worlds,raw['background_prior'])
        np.testing.assert_allclose(weights,np.ones(9)/9,atol=1e-14,rtol=0)
        hidden=row['origin']['hidden_cells'];assert len(hidden)==2 and hidden[0][0]!=hidden[1][0]
        if row['arm']=='shared_goal_mask':
            assert hidden[0][1]==hidden[1][1]
            members={a['player_id']for a in raw['game']['goals'][hidden[0][1]]['required_actions']}
            assert {p for p,g in hidden}<=members
        assert sorted(raw['game']['n_actions_per_player'])==[1,1,2]
        # Every legal world is generated, independently of the unused masked public draw.
        for p,g in hidden:assert {w[p][g]for w in rules.worlds}=={-1,0,1}
    for a,b in zip(rows[::2],rows[1::2]):
        assert a['raw']['game']==b['raw']['game']
        assert a['origin']['public_preference_draw']==b['origin']['public_preference_draw']
        assert generate_pair(a['pair_id'],**{k:a['configuration'][k]for k in ('goals','geometry','scoring')})==[a,b]
    return dict(parents=24,pairs=12,worlds_each=9,deterministic_rebuild=True,
        pair_geometry_public_draw_order_matched=True,uniform_independent_hidden_prior=True,
        identical_mask_pairs=[a['pair_id']for a,b in zip(rows[::2],rows[1::2])if a['raw']==b['raw']],
        canonical_distinct=len({r['canonical_id']for r in rows}),
        checks='No payoff/Q/S admission; all-neutral/avoid/public-want draws retained; no duplicate rejection')


def freeze(args):
    config=json.loads(REG.read_text())['parameters']
    snapshot(args.output,dict(operation='freeze_and_validate_raw_pilot',**config))
    rows=[]
    for pair,(goals,geometry,scoring)in enumerate(product((3,4),('split','bundled'),('binary','mixed','linear'))):
        rows.extend(generate_pair(pair,goals,geometry,scoring))
    checks=validate(rows)
    for row in rows:
        row['preflight']=count_public_tree(StrategicRules(row['raw']))
        assert row['preflight']['public_histories']<=600000
    (args.output/'parents.jsonl').write_text(''.join(stable(r)+'\n'for r in rows))
    write(args.output/'VALIDATION.json',checks)
    write(args.output/'manifest.json',dict(**checks,parents_sha256=sha(args.output/'parents.jsonl'),
        snapshot_sha256=sha(args.output/'pipeline_snapshot.json'),status='RAW_FROZEN_NOT_TRAINING_READY',
        pilot_indices=config['local_pilot_indices'],preflight_node_range=[min(r['preflight']['public_histories']for r in rows),max(r['preflight']['public_histories']for r in rows)]))
    print(stable(json.loads((args.output/'manifest.json').read_text())),flush=True)


def main():
    if len(sys.argv)>1 and sys.argv[1]in ('run','audit','doctor'):
        remote.REG,remote.VERSION,remote.snapshot=REG,VERSION,snapshot
        remote.main();return
    p=argparse.ArgumentParser();p.add_argument('command',choices=['freeze']);p.add_argument('--output',type=Path,required=True)
    freeze(p.parse_args())


if __name__=='__main__':main()
