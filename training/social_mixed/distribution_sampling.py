"""Balanced kernel/profile scheduling with intact semantic contrast units."""
from collections import defaultdict
import random
from training.b_sft.preference_contract import VERSION,PROFILES

def groups(rows):
 units=defaultdict(list)
 for t in rows:
  if not t.get('training_ready') or t.get('contract_version')!=VERSION:raise ValueError('Unreviewed distribution task')
  k=t['kernel'];mode=t['completion_mode'];profile=t['background_profile']
  if k=='B3':case=t.get('b3_case','previous_belief')
  elif k=='B1':case=t.get('b12_case',t.get('b_lesson',t.get('origin_id')))
  elif k=='B2':case=t.get('b12_case',t.get('origin_id'))
  elif k=='P2':
   name=t.get('p123_case','retained');case='joint_correlation' if name.startswith('joint') else 'belief_weights' if name.startswith('weight') else name
  elif k=='P3':case='qualitative_contrasts'
  elif k=='P4':case='acquisition_and_use' if t.get('p4_case') in ('acquisition','answer_use','deadline') else t.get('p4_case',t['origin_id'])
  else:
   name=t.get('p123_case',t['origin_id']);case='response_own' if name in ('response_own_gain','response_own_loss') else 'response_social' if name in ('response_helpful_tie','response_harmful_tie') else name
  # Keep scoring contrasts together, but use one background per unit/update.
  units[k,profile,case].append(t)
 return {k:sorted(v,key=lambda t:t['id']) for k,v in units.items()}

def select(rows,step,seed,validation=False):
 units=groups(rows);step=0 if validation else step;selected=[];profiles=list(PROFILES)
 schedule=[(('B1','B2','B3')[step%3],(step//3)%4,step//12),
           (('P1','P2','P3','P4')[step%4],(step//4)%4,step//16)]
 if validation:
  schedule=[(k,0,0) for k in ('B1','B2','B3','P1','P2','P3','P4')]
 for kernel,pi,cycle in schedule:
  available=sorted(k for k in units if k[0]==kernel)
  if not available:
   if validation:continue
   raise ValueError('Missing kernel '+kernel)
  p=profiles[pi];options=[k for k in available if k[1]==p]
  if not options:raise ValueError('Missing kernel/profile '+kernel+'/'+p)
  unit=options[cycle%len(options)];selected+=units[unit]
 # Add complete B control units if a sampled batch lacks one set-size role.
 for full in (True,False):
  if not any(t['task']=='B' and (len(t['teacher']['gold']['possible_preferences'])==3)==full for t in selected):
   candidates=[k for k,v in units.items() if k[0].startswith('B') and any((len(t['teacher']['gold']['possible_preferences'])==3)==full for t in v)]
   if candidates:
    selected+=units[sorted(candidates)[step%len(candidates)]]
 selected=list({t['id']:t for t in selected}.values());random.Random(f'{seed}:distribution:{step}').shuffle(selected)
 return selected
