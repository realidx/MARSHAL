"""Sample certified contrast units, never filter by model success."""
from collections import defaultdict
import random

def units(rows):
 groups=defaultdict(list)
 for t in rows:
  if not t.get('training_ready') or t.get('contract_version')!='plain-v1':raise ValueError('Unreviewed task in active pack')
  k=t['kernel']
  if k=='B3':key=(k,'previous-belief-controls')
  elif k=='B1':key=(k,'final-response-controls')
  elif k=='P2':
   case=t.get('p123_case','retained')
   family='joint' if case.startswith('joint') else 'weights' if case.startswith('weight') else case
   key=(k,family)  # Keep binary/linear and belief contrasts together.
  elif k=='P1':key=(k,t.get('p123_case',t['id']).replace('response_own_gain','response_own').replace('response_own_loss','response_own').replace('response_helpful_tie','response_social').replace('response_harmful_tie','response_social'))
  else:key=(k,t.get('p4_case',t['id']))
  groups[key].append(t)
 return {k:sorted(v,key=lambda t:t['id']) for k,v in groups.items()}

def select(rows,step,seed,validation=False):
 by=units(rows);rng=random.Random(f'{seed}:contract:{0 if validation else step}')
 chosen=[]
 # All retained B3 controls stay together, including full-set and singleton
 # previous beliefs. Add one complete B1 unit, rather than row-count sampling.
 for kernel in ('B3','B1'):
  options=sorted(k for k in by if k[0]==kernel)
  if not options:raise ValueError(f'Missing certified {kernel} controls')
  chosen+=by[options[(0 if validation else step)%len(options)]]
 b=[t for t in chosen if t['task']=='B']
 if not validation and (not any(len(t['teacher']['gold']['possible_preferences'])==3 for t in b) or not any(len(t['teacher']['gold']['possible_preferences'])<3 for t in b)):raise ValueError('B full-set/shrink contrast missing')
 # Kernels receive scheduled units, not probability proportional to row count.
 for kernel in ('P1','P2','P4'):
  options=sorted(k for k in by if k[0]==kernel)
  if options:chosen+=by[options[(0 if validation else step)%len(options)]]
 rng.shuffle(chosen)
 assert len({t['id'] for t in chosen})==len(chosen)
 return chosen
