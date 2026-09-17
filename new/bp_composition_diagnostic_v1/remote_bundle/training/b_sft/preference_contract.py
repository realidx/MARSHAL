"""Public background weights and task-specific, explicitly distinct tolerances."""
import numpy as np
VERSION='public-prior-margin-v1'
PROFILES={'balanced':(1,1,1),'want_heavy':(2,1,1),'neutral_heavy':(1,2,1),'avoid_heavy':(1,1,2)}
B_MARGIN=.1
P_TOLERANCE=.1
NAMES=('want','neutral','avoid')
VALUES=(1,0,-1)
def profile(name):
 weights=PROFILES[name]
 return dict(version=VERSION,name=name,weights=dict(zip(NAMES,weights)))
def world_weights(worlds,prior):
 weights=prior['weights']
 if set(weights)!=set(NAMES) or any(not np.isfinite(v) or v<0 for v in weights.values()) or sum(weights.values())<=0:raise ValueError('Invalid background weights')
 mass=np.array([np.prod([weights[NAMES[VALUES.index(v)]] for row in w for v in row]) for w in worlds],float)
 if not np.isfinite(mass).all() or mass.sum()<=0:raise ValueError('Invalid background support')
 return mass/mass.sum()
def belief(mass,margin=B_MARGIN):
 if margin<0:raise ValueError('Negative belief margin')
 if any(v<0 for v in mass.values()) or not np.isclose(sum(mass.values()),1):raise ValueError('Invalid belief')
 possible=[n for n in NAMES if mass.get(n,0)>0]
 ranked=sorted(possible,key=lambda n:mass[n],reverse=True)
 favored=ranked[0] if len(ranked)==1 or mass[ranked[0]]-mass[ranked[1]]>margin+1e-9 else 'undetermined'
 return dict(possible_preferences=possible,favored=favored)
def description(prior,public_fixed=False):
 w=prior['weights'];total=sum(w.values())
 text='Background preference distribution: '+', '.join(f'{n} {100*w[n]/total:g}%' for n in NAMES)+'. '
 text+=('Publicly fixed preferences remain as shown. For every other player-goal preference, ' if public_fixed else 'For each player-goal preference, ')
 return text+('these are the independent background chances before applying the game conditions. '
  'Each player wants at least one goal, and every goal has at least one non-neutral player. '
  'Your own preferences, known facts and observed choices can change your current belief. '
  'Everyone knows this background. Preferences stay fixed throughout the game.')
