"""Audit old resets; generate independent native full games without outcome filters."""
from collections import Counter
from dataclasses import asdict
from itertools import combinations,product
import hashlib,json
from pathlib import Path
import numpy as np
from training.b_sft.build_bp_pilot import topology
from training.social_mixed.core import Episode,seed_for
from training.social_mixed.frozen.benac_p.generator import GeneratorConfig,generate_game
from training.social_mixed.frozen.outcome_rules import generation_rule
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'examples/social_mixed/selfplay_audit_v2'
SEED=20260916

def read(path):return [json.loads(s) for s in path.read_text().splitlines()]
def stable(x):return json.dumps(x,sort_keys=True,separators=(',',':'))
def sha(x):return hashlib.sha256(stable(x).encode()).hexdigest()
def geometry(r):return topology(r['raw'])
def classify(r):
 g=r['raw']['game'];n=g['n_players'];goals=g['goals'];world=r['realized_world'];rounds=len(g['round_robin'])//n
 mode='binary' if all(x['binary'] for x in goals) else 'linear' if not any(x['binary'] for x in goals) else 'mixed'
 conflicts=sum(any(world[p][q]>0 for p in range(n)) and any(world[p][q]<0 for p in range(n)) for q in range(len(goals)))
 sets=[{(a['player_id'],a['action_id']) for a in goal['required_actions']} for goal in goals]
 shared=sum(bool(a&b) for a,b in combinations(sets,2))
 tags=['proposal_response_inference','private_information','investigation_available']
 if shared:tags.append('shared_commitment_payoffs')
 if conflicts:tags.append('opposed_goal_preferences')
 if n==3:tags.append('third_player_effects')
 if rounds>=3:tags.append('cumulative_public_evidence_opportunity')
 if mode!='binary':tags.append('partial_completion')
 shared_wants=sum(sum(world[p][q]==1 for p in range(n))>=2 for q in range(len(goals)))
 tags.append('shared_positive_interests' if shared_wants else 'distinct_positive_interests')
 offsets=np.cumsum([0]+g['n_actions_per_player']);utilities=[]
 for bits in product((0,1),repeat=int(offsets[-1])):
  satisfaction=[]
  for goal in goals:
   flags=[bits[offsets[a['player_id']]+a['action_id']] for a in goal['required_actions']]
   satisfaction.append(float(all(flags)) if goal['binary'] else sum(flags)/len(flags))
  utilities.append(np.array(world)@satisfaction)
 utilities=np.array(utilities);maxima=utilities.max(axis=0)
 common=bool(np.any(np.all(np.isclose(utilities,maxima),axis=1)))
 hidden=(n-1)*len(goals);width=g['n_actions_per_player']
 initial_actions=max(1+hidden+sum((1+width[p])*(1+width[q])-1 for q in range(n) if q!=p) for p in range(n))
 max_arity=max(len(goal['required_actions']) for goal in goals)
 hint='D3' if rounds>=4 or initial_actions>=24 or (max_arity>=3 and hidden>=6) else 'D1' if n==2 and rounds==2 and hidden<=3 and initial_actions<=13 and shared<=2 else 'D2'
 return dict(id=r['id'],split=r['split'],geometry=geometry(r),players=n,goals=len(goals),rounds=rounds,
  completion=mode,prior_values=r['raw']['preference_generation']['values'],difficulty_hint=hint,
  difficulty_axes=dict(hidden_slots_per_player=hidden,initial_max_action_count=initial_actions,max_goal_arity=max_arity,shared_goal_pairs=shared,proposal_opportunities=n*rounds),
  difficulty_basis='Structural workload hint only; not model-calibrated or a solver label.',
  social_tags=tags,conflicting_goals=conflicts,shared_goal_pairs=shared,
  shared_want_goals=shared_wants,physical_common_individual_maximum=common,
  physical_utility_min=utilities.min(axis=0).tolist(),physical_utility_max=maxima.tolist(),
  physical_scope='All commitment bit patterns; not horizon reachability, strategic solvability, or guaranteed reward variance. Never used for admission or sampling.',
  realized_payoff_pattern='opposed_on_some_goals' if conflicts else 'no_within_goal_opposition',
  investigation_value='unmeasured',reasoning_quality='unmeasured',reward_variance='unmeasured')

def summarize(rows):
 c=[classify(r) for r in rows]
 return dict(count=len(rows),geometries=len({r['geometry'] for r in c}),
  indexed_game_worlds=len({sha([r['raw']['game'],r['realized_world']]) for r in rows}),
  counts={k:dict(Counter(str(r[k]) for r in c)) for k in ('players','rounds','completion','prior_values','difficulty_hint','realized_payoff_pattern')})

def build():
 old=read(ROOT/'examples/social_mixed/data/selfplay_train.jsonl')
 validation=read(ROOT/'examples/social_mixed/data/selfplay_validation.jsonl')
 evaluation=json.loads((ROOT/'runs/outcome_selfplay_screen/eval_splits.json').read_text())
 test=[r for r in evaluation['records'] if r['split']=='test']
 held={geometry(r) for r in validation+test};attempts=[];new=[]
 # Balanced modes and prior supports, 2:1 player ratio; knobs fixed before any rollouts.
 for players in (2,3):
  for mode in ('binary','linear','mixed'):
   for law in ('foundation','adaptation'):
    for j in range(4 if players==2 else 2):
     rounds=([2,3,4,5][j] if players==2 else [2,4][j])
     goals=(3+j%2) if players==2 else 3
     cfg=GeneratorConfig(n_players=players,actions_per_player=(2+j%2) if players==2 else 2,
      n_goals=goals,n_rounds=rounds,preference_probs=(.5,.5,0) if law=='foundation' else (1/3,1/3,1/3),
      linear_goal_fraction={'binary':0.,'linear':1.,'mixed':.5}[mode])
     for attempt in range(100):
      seed=seed_for(SEED,'native-bank',players,mode,law,j,attempt);spec=generate_game(seed,cfg)
      game=spec.to_dict();world=spec.private_preferences.tolist();game.pop('private_preferences',None)
      for key in ('metadata','seed'):game.pop(key,None)
      raw=dict(game=game,history=[],preference_generation=generation_rule(law))
      r=dict(id=f'random-v2-{players}p-{mode}-{law}-{j}',split='train',players=players,rounds=rounds,
       raw=raw,realized_world=world,generation=dict(seed=seed,config=json.loads(json.dumps(asdict(cfg))),attempt=attempt,source='native generate_game; no teaching prefix or outcome selection'))
      conflict=geometry(r) in held
      attempts.append(dict(id=r['id'],seed=seed,geometry=geometry(r),status='heldout_geometry_excluded' if conflict else 'admitted'))
      if not conflict:new.append(r);break
     else:raise RuntimeError('Could not allocate train geometry without heldout overlap')
 # One index per mode/support/player stratum, predetermined alternation covers longer horizons.
 selected=[]
 for players in (2,3):
  for mi,mode in enumerate(('binary','linear','mixed')):
   for li,law in enumerate(('foundation','adaptation')):
    choices=[r for r in new if r['players']==players and classify(r)['completion']==mode and r['raw']['preference_generation']['values']==generation_rule(law)['values']]
    index=(mi+li)%(4 if players==2 else 2)
    selected.append(choices[index])
 # Existing validation: deterministic configuration coverage; no realized preference/outcome selection.
 chosen=[];covered=set()
 while len(chosen)<4:
  def features(r):
   c=classify(r);return {('players',c['players']),('rounds',c['rounds']),('mode',c['completion']),('prior',str(c['prior_values'])),('geometry',c['geometry'])}
  r=min((r for r in validation if r not in chosen),key=lambda r:(-len(features(r)-covered),sha([SEED,r['id']])))
  chosen.append(r);covered|=features(r)
 selected+=chosen
 return old,validation,test,new,selected,attempts

def main():
 old,val,test,new,selected,attempts=build();OUT.mkdir(parents=True,exist_ok=True);files={}
 def write(name,rows):
  data=''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows).encode();(OUT/name).write_bytes(data)
  files[name]=dict(count=len(rows),sha256=hashlib.sha256(data).hexdigest())
 write('train_candidate.jsonl',new);write('probe_resets.jsonl',selected)
 write('old_classification.jsonl',[classify(r) for r in old+val+test]);write('candidate_classification.jsonl',[classify(r) for r in new])
 write('probe_classification.jsonl',[classify(r) for r in selected]);write('generation_attempts.jsonl',attempts)
 banks={'old_train':old,'validation':val,'test':test,'candidate_train':new}
 overlap={f'{a}/{b}':sorted({geometry(r) for r in banks[a]}&{geometry(r) for r in banks[b]}) for a,b in combinations(banks,2)}
 report=dict(version='selfplay-audit-v2',banks={k:summarize(v) for k,v in banks.items()},geometry_overlap=overlap,
  old_source='curriculum.py SELECTION: six chosen named templates; foundation=linear/[0,1], adaptation=mixed/[-1,0,1], tradeoffs=binary/[-1,0,1]. Random hidden worlds and round permutations do not make these independently generated random geometries.',
  structural_key='Permutation-invariant player/action/goal incidence, including action counts. Ignores scoring, preferences, rounds. Shared structure is dependence, not automatically leaked answers.',
  probe=dict(resets=len(selected),train=sum(r['split']=='train' for r in selected),validation=sum(r['split']=='validation' for r in selected),replicas=4,full_games=len(selected)*4,concurrency_per_endpoint=16,max_tokens=1024),
  seed=SEED,files=files,training_ready=False,model_tested=False,merged=False,test_sampled=False,
  generation='Native random game generator; legal zero state, no solver call. Only exclude existing heldout geometry from new train. Duplicate new train geometries retained and reported, not outcome-filtered.',
  source_hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [ROOT/'examples/social_mixed/data/selfplay_train.jsonl',ROOT/'examples/social_mixed/data/selfplay_validation.jsonl',ROOT/'runs/outcome_selfplay_screen/eval_splits.json',ROOT/'runs/outcome_selfplay_screen/curriculum.py',ROOT/'training/social_mixed/frozen/benac_p/generator.py']})
 (OUT/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps(dict(banks=report['banks'],overlap=overlap,probe=report['probe']),ensure_ascii=False))
if __name__=='__main__':main()
