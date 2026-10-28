"""Freeze 100 raw parent games before any solver, Q/S/D or model measurement."""
from collections import Counter
from hashlib import sha256
from itertools import combinations,product
import json
from pathlib import Path
import platform
import shutil
import sys

import numpy as np

from new.strategic_game_v1_20261021.rules import VERSION,StrategicRules
from new.game_design_feasibility_20261021.design import count_public_tree
from training.b_sft.preference_contract import profile,world_weights
from training.strategic_slices.oracle_consistent import canonical_parent
from training.strategic_slices.build import structural_family

ROOT=Path(__file__).resolve().parents[2]
POOL_VERSION='strategic-parents-100-two-round-unknown-query-v1'


def write(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x') as f:
        json.dump(obj,f,ensure_ascii=False,indent=2);f.write('\n')


def stable(obj):
    return json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(',',':'))


def generate(seed,*,players,goals,hidden):
    counts=[2]*players if players==2 else [1]*players
    rng_top,rng_mode,rng_mask,rng_public,rng_order=[np.random.default_rng(s)
        for s in np.random.SeedSequence(seed).spawn(5)]
    refs=[(p,a) for p,k in enumerate(counts) for a in range(k)]
    possible=[subset for k in range(2,min(3,len(refs))+1)
        for subset in combinations(refs,k) if len({p for p,a in subset})>=2]
    # Structural acceptance only. Separate RNGs leave preference draws and
    # visibility independent of this rejection process.
    attempts=0
    while True:
        attempts+=1
        chosen=[possible[int(i)] for i in rng_top.choice(len(possible),goals,replace=False)]
        if set().union(*(set(g) for g in chosen))==set(refs):
            break
    target_goals=[dict(goal_id=g,binary=bool(rng_mode.integers(2)),
        required_actions=[dict(player_id=p,action_id=a) for p,a in required])
        for g,required in enumerate(chosen)]
    cells=[(p,g) for p in range(players) for g in range(goals)]
    masked={cells[int(i)] for i in rng_mask.choice(len(cells),hidden,replace=False)}
    fixed=rng_public.choice([1,0,-1],size=(players,goals))
    catalogues={}
    for p in range(players):
        slots=[g for g in range(goals) if (p,g) in masked]
        rows=[]
        for values in product([1,0,-1],repeat=len(slots)):
            row=fixed[p].tolist()
            for g,v in zip(slots,values):row[g]=v
            rows.append(row)
        catalogues[str(p)]=rows
    order=list(map(int,rng_order.permutation(players)))
    raw=dict(game=dict(n_players=players,n_actions_per_player=counts,goals=target_goals,
        round_robin=order*2,max_changes=1,menu_enabled=False,
        investigation_budget=1,offer_budget=1),
        ego=0,own_preferences=catalogues['0'][0],type_catalogues=catalogues,
        background_prior=profile('balanced'),history=[])
    return raw,dict(structural_draws=attempts,hidden_cells=sorted(map(list,masked)))


def specifications():
    # 67/33 follows the user's earlier allowed approximate 2:1 player ratio.
    # Round count is uniformly two, not the earlier 70 short/30 long pool.
    return ([dict(players=2,goals=3,hidden=2)]*17+
        [dict(players=2,goals=4,hidden=2)]*17+
        [dict(players=2,goals=3,hidden=3)]*17+
        [dict(players=2,goals=4,hidden=3)]*16+
        [dict(players=3,goals=3,hidden=1)]*17+
        [dict(players=3,goals=4,hidden=1)]*16)


def main():
    out=Path('new/strategic_game_v1_20261021/parents_100_v1')
    out.mkdir(parents=True,exist_ok=False)
    specs=specifications()
    order=np.random.default_rng(2026102109).permutation(len(specs))
    parents=[]; seen=set(); rejections=[]
    for index,slot in enumerate(order):
        config=specs[int(slot)];attempt=0
        while True:
            seed=202610240000+index*1000+attempt
            raw,origin=generate(seed,**config)
            canonical=canonical_parent(raw)
            if canonical not in seen:break
            rejections.append(dict(index=index,seed=seed,reason='renaming-equivalent duplicate parent'))
            attempt+=1
        seen.add(canonical)
        rules=StrategicRules(raw); counts=count_public_tree(rules)
        if counts['node_world_pairs']>300000:
            raise AssertionError('Chosen parameter band exceeded declared resource-count envelope')
        probs=world_weights(rules.worlds,raw['background_prior'])
        np.testing.assert_allclose(probs,np.full(len(probs),1/len(probs)),atol=1e-14,rtol=0)
        identity=dict(game_version=VERSION,raw=raw)
        pid=sha256(stable(identity).encode()).hexdigest()[:24]
        parent=dict(index=index,id=pid,canonical_id=canonical,
            structural_family=structural_family(raw['game']),raw=raw,
            configuration=config,seed=seed,origin=origin,preflight=counts,
            oracle_status='NOT_ATTEMPTED',Q_S_D_status='NOT_MEASURED')
        parents.append(parent)
    with (out/'parents.jsonl').open('x') as f:
        for p in parents:f.write(stable(p)+'\n')
    sources=['new/strategic_game_v1_20261021/rules.py','new/strategic_game_v1_20261021/pool.py',
        'new/game_design_feasibility_20261021/design.py','training/b_sft/social_private_teacher.py',
        'training/b_sft/social_terminal_teacher.py','training/b_sft/shared_teacher.py',
        'training/b_sft/preference_contract.py','training/strategic_slices/oracle_consistent.py',
        'training/strategic_slices/build.py','third_party/negotiation_benchmark/src/benac_p/schema.py',
        'third_party/negotiation_benchmark/src/benac_p/state.py','third_party/negotiation_benchmark/src/benac_p/endgame.py']
    hashes={rel:sha256((ROOT/rel).read_bytes()).hexdigest() for rel in sources}
    for rel in sources:
        dst=out/'source'/rel;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/rel,dst)
    resolved=dict(players={'2':67,'3':33},rounds=2,investigation_budget=1,offer_budget=1,
        new_commitments_per_offer_per_party=1,actions={'2':[2,2],'3':[1,1,1]},
        goals=[3,4],hidden_cells={'2':[2,3],'3':[1]},
        prior=dict(want=1/3,neutral=1/3,avoid=1/3,independent=True,public=True),
        world_support={'2':[9,27],'3':[3]},goal_required_commitments=[2,3],
        goal_scoring='independent binary/linear 50/50 per goal',
        structural_admission='Each declared commitment occurs in a goal; no duplicate requirement set',
        preference_admission='No forced want, no exclusion of all-neutral/avoid types or goals',
        duplicate_admission='Reject exact games equivalent under player/action/goal renaming; no metric-based filtering',
        information='Public fixed preferences + own full preferences + accumulated own direct investigation answers + full public action history',
        investigation_targets='Other-player nonpublic cells not directly investigated before; no utility/posterior/true-world filtering',
        offer_cost='One per-player quota charged on proposal, never refunded; no extra utility penalty',
        response_ties='Own expected terminal utility first, then other-player sum only for ACCEPT/REJECT',
        horizon='Current node through native terminal; no approximate nonterminal leaf',
        membership='All 100 fixed before solver/Q/S/D/model calls; failures stay attached, never replaced',
        splits='NOT_ASSIGNED; no selection/evaluation yet')
    snapshot=dict(version=POOL_VERSION,status='RAW_PARENTS_FROZEN_NOT_TRAINING_READY',
        actual_argv=sys.argv,resolved_config=resolved,sources=hashes,
        environment=dict(python=sys.version,numpy=np.__version__,executable=sys.executable,
            platform=platform.platform()),
        sampling=dict(configuration_shuffle_seed=2026102109,
            seed_formula='202610240000+index*1000+duplicate_retry',components='5 independent SeedSequence streams',
            structural_rejection='Only geometry; independent of preference RNG',model_calls=0),
        reward_advantage_training='NOT_APPLICABLE: parent generation only',
        production='Unchanged v8; no prompt or training activation',
        model_data_identity='Model not used; exact parent data hash in manifest')
    write(out/'pipeline_snapshot.json',snapshot)
    manifest=dict(version=POOL_VERSION,status=snapshot['status'],parents=len(parents),
        distinct_canonical_parents=len(seen),families=len({p['structural_family'] for p in parents}),
        configuration_counts=dict(Counter(stable(p['configuration']) for p in parents)),
        raw_sha256=sha256((out/'parents.jsonl').read_bytes()).hexdigest(),
        snapshot_sha256=sha256((out/'pipeline_snapshot.json').read_bytes()).hexdigest(),
        duplicate_rejections=rejections,
        structural_draws=sum(p['origin']['structural_draws'] for p in parents),
        all_native_rounds=2,oracle_profiles=0,S_D_measured=False,training_compatible=False,
        limits='Raw parent pool only; source-matched solver statuses belong to separate audits. No model effects measured.')
    write(out/'manifest.json',manifest)
    print(json.dumps({k:manifest[k] for k in ('version','parents','distinct_canonical_parents','families','raw_sha256')},ensure_ascii=False))


if __name__=='__main__':main()
