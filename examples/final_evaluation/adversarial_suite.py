"""Freeze paired ID / incidence-OOD BENAC full games without model selection."""
import argparse
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import random
import numpy as np
from training.social_mixed.core import ROOT, Episode, seed_for
DATA=ROOT/'examples/social_mixed/data_reasoning_v5_candidate'
def load_data():
    return {n:[json.loads(l) for l in (DATA/(n+'.jsonl')).read_text().splitlines()] for n in ('bp_train','bp_validation','selfplay_train','selfplay_validation')}
from training.social_mixed.structure_coverage import geometry_id
from training.social_mixed.frozen.benac_p.generator import GeneratorConfig, generate_game

DEFAULT = ROOT/'examples/final_evaluation/adversarial_v2'
SEED = 2026091902

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def fingerprint(row):
    return json.dumps([row['raw']['game'], row['realized_world']], sort_keys=True)

def redraw(row, seed):
    """Exact public generation law: independent slots conditioned on native constraints."""
    rng = np.random.default_rng(seed)
    weights = row['raw']['preference_generation']['background_prior']['weights']
    probs = np.array([weights[k] for k in ('want','neutral','avoid')],dtype=float)
    probs /= probs.sum()
    for attempt in range(10000):
        world = rng.choice([1,0,-1],size=(3,3),p=probs)
        if all(any(v==1 for v in r) for r in world) and all(any(world[:,g]!=0) for g in range(3)):
            return world.tolist(), attempt
    raise RuntimeError('Preference rejection budget exhausted')

def build(folder):
    data=load_data()
    sources={str((DATA/(name+'.jsonl')).relative_to(ROOT)):digest(DATA/(name+'.jsonl')) for name in data}
    # Check both learning domains and already-used validation; no scoring/timing in geometry key.
    seen={geometry_id(r.get('raw',r.get('input'))['game']) for rows in data.values() for r in rows}
    old=[json.loads(l) for l in (ROOT/'examples/final_evaluation/benac_a_v1/resets.jsonl').read_text().splitlines()]
    seen.update(geometry_id(r['raw']['game']) for r in old if r['evaluation_split']=='OOD')
    worlds={fingerprint(r) for name,rows in data.items() if name.startswith('selfplay') for r in rows}
    worlds.update(fingerprint(r) for r in old)
    train=[r for r in data['selfplay_train'] if r['players']==3]
    rows=[];used_ood=set();attempts=[]
    for binary in (True,False):
        for rounds in (2,4):
            for profile in ('balanced','avoid_heavy'):
                candidates=[r for r in train if r['rounds']==rounds and r['background_profile']==profile and all(g['binary']==binary for g in r['raw']['game']['goals'])]
                source=min(candidates,key=lambda r:seed_for(SEED,'source',r['id']))
                pair=f'{"binary" if binary else "linear"}-{rounds}r-{profile}'
                for split in ('ID','OOD'):
                    row=deepcopy(source);row.update(id=f'A-{split}-{pair}',split='test',evaluation_split=split,pair_id=pair,origin_id=source['id'])
                    if split=='OOD':
                        cfg=GeneratorConfig(n_players=3,actions_per_player=2,n_goals=3,n_rounds=rounds,linear_goal_fraction=0.0 if binary else 1.0)
                        for attempt in range(10000):
                            seed=seed_for(SEED,pair,'geometry',attempt)
                            game=generate_game(seed,cfg).to_dict()
                            # Broader native-valid incidence: a goal may require
                            # two commitments owned by the same player. Scale fixed.
                            rng=random.Random(seed)
                            for goal in game['goals']:
                                while True:
                                    refs=rng.sample([(p,a) for p in range(3) for a in range(2)],rng.choice((2,3,4)))
                                    if len({p for p,a in refs})>=2:break
                                goal['required_actions']=[dict(player_id=p,action_id=a) for p,a in sorted(refs)]
                            for key in ('private_preferences','seed','metadata'):game.pop(key,None)
                            # Keep timing and all scale constraints matched to the ID member.
                            game['round_robin']=deepcopy(source['raw']['game']['round_robin'])
                            family=geometry_id(game)
                            admitted=family not in seen and family not in used_ood
                            attempts.append(dict(pair=pair,seed=seed,family=family,admitted=admitted))
                            if admitted:break
                        else:raise RuntimeError('No independent geometry found')
                        row['raw']['game']=game;used_ood.add(family)
                        row['geometry_generation']=dict(seed=seed,config=asdict(cfg),attempt=attempt,source='native base plus seeded 2/3/4-commitment goal incidence; ownership retained; geometry exclusion only')
                    for attempt in range(10000):
                        seed=seed_for(SEED,row['id'],'world',attempt)
                        row['realized_world'],rejections=redraw(row,seed)
                        if fingerprint(row) not in worlds:break
                    else:raise RuntimeError('No new world found')
                    row['preference_redraw']=dict(seed=seed,rejection_count=rejections,duplicate_attempt=attempt,source='public weighted prior; no outcome filtering')
                    row['structure_family']=geometry_id(row['raw']['game'])
                    worlds.add(fingerprint(row));rows.append(row)
    from examples.final_evaluation.adversarial_runtime import witnesses
    proofs={r['id']:witnesses(r) for r in rows}
    folder.mkdir(parents=True,exist_ok=False)
    (folder/'witnesses.json').write_text(json.dumps(proofs,indent=2)+'\n')
    (folder/'resets.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
    (folder/'generation_attempts.json').write_text(json.dumps(attempts,indent=2)+'\n')
    from training.social_mixed import policy_prompt
    code_paths=[Path(__file__),ROOT/'training/social_mixed/core.py',ROOT/'training/social_mixed/weighted_rules.py',ROOT/'training/social_mixed/policy_prompt.py']
    code_paths += [ROOT/'examples/final_evaluation/adversarial_runtime.py', ROOT/'examples/final_evaluation/adversarial_checks.py',ROOT/'examples/final_evaluation/adversarial.py',ROOT/'examples/final_evaluation/launch_benac_a.py']
    code_paths+=sorted((ROOT/'training/social_mixed/frozen').rglob('*.py'))
    manifest=dict(version='adversarial-v2',seed=SEED,resets=16,seats=[0,1,2],games_per_model=144,replicas=3,q0_shared_trajectories=48,
        opponents=['Q0','Q0'],sampling=dict(temperature=1.0,top_p=1.0,max_tokens=1024),
        retries=1,selection='No LLM outcomes, utility filters or solver feasibility used',
        id_definition='Seen training geometry with new indexed preference world; not structural generalization',
        ood_definition='Dependency incidence non-isomorphic to current BP/SP train and validation, ignoring labels, scoring and timing',
        source_hashes=sources,code_hashes={str(p.relative_to(ROOT)):digest(p) for p in code_paths},
        files={name:digest(folder/name) for name in ('resets.jsonl','generation_attempts.json','witnesses.json')},
        teacher_condition='Not included: exact same-information teacher scope/off-path policy not validated',
        structure_counts={s:len({r['structure_family'] for r in rows if r['evaluation_split']==s}) for s in ('ID','OOD')})
    (folder/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest

def load(folder=DEFAULT):
    m=json.loads((folder/'manifest.json').read_text())
    for name,sha in m['files'].items():
        if digest(folder/name)!=sha:raise ValueError(f'Frozen file changed: {name}')
    for name,sha in (m['source_hashes']|m['code_hashes']).items():
        if digest(ROOT/name)!=sha:raise ValueError(f'Source changed since freeze: {name}')
    return m,[json.loads(l) for l in (folder/'resets.jsonl').read_text().splitlines()]

def check(folder):
    _,rows=load(folder);count=0
    from training.social_mixed.test_core import legal_response
    for row in rows:
        for replica in range(3):
            ep=Episode(row,row['id'],replica,SEED);rng=random.Random(seed_for(SEED,row['id'],replica))
            while ep.status=='running':ep.accept(legal_response(ep,rng))
            assert ep.status=='terminal';count+=1
    return dict(scripted_complete_games=count,model_calls=0)

if __name__=='__main__':
    cli=argparse.ArgumentParser();cli.add_argument('--output',type=Path,default=DEFAULT);cli.add_argument('--build',action='store_true');a=cli.parse_args()
    if a.build:print(json.dumps(build(a.output),indent=2))
    print(json.dumps(check(a.output)))
