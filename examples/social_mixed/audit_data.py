"""Read-only dataset audit and deterministic diagnostic selection; no model calls."""
import collections as C
import hashlib
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
DATA=ROOT/'examples/social_mixed/data'
OUT=ROOT/'examples/social_mixed/audit_v1'
def stable(x):return json.dumps(x,sort_keys=True,separators=(',',':'))
def sha(x):return hashlib.sha256(stable(x).encode()).hexdigest()
def count(xs):return dict(sorted(C.Counter(map(str,xs)).items()))
def geometry(t,sp=False):
 g=t['raw']['game'] if sp else t['input']['game']
 # Exact indexed goal/action incidence. Not a graph-isomorphism certificate.
 return sha({k:g.get(k) for k in ('n_players','n_actions_per_player','goals','max_changes','forbidden_actions')})
def features(t,sp=False):
 if sp:
  g=t['raw']['game'];return {'geometry:'+geometry(t,True),'players:'+str(t['players']),'rounds:'+str(t['rounds']),'prior:'+stable(t['raw']['preference_generation']['values']),'completion:'+str([x['binary'] for x in g['goals']]),'level:'+str(t.get('level','validation'))}
 out={'pool:'+t['pool'],'family:'+t['family'],'source:'+t['training_source']}
 if t['task']=='B':out|={'gold:'+stable(t['teacher']['gold']),'history:'+stable(t['input'].get('voluntary_history',[])),'prior:'+stable(t['input'].get('old_belief'))}
 else:out|={'actions:'+stable(sorted({a['action'] for a in t['teacher']['acceptable_actions']})),'information:'+str(any(a['action']=='INVESTIGATE' for a in t['teacher']['acceptable_actions']))}
 return out
def select(rows,n,sp=False,required=()):
 selected=list(required); seen=set().union(*(features(t,sp) for t in selected)) if selected else set()
 while len(selected)<n:
  candidates=[t for t in rows if t not in selected]
  chosen=min(candidates,key=lambda t:(-len(features(t,sp)-seen),sha(['probe-20260915',t['id']])))
  selected.append(chosen);seen|=features(chosen,sp)
 return selected

def main():
 OUT.mkdir(exist_ok=True)
 banks={p.stem:[json.loads(s) for s in p.read_text().splitlines()] for p in sorted(DATA.glob('*.jsonl'))}
 manifest=json.loads((DATA/'manifest.json').read_text())
 for name,rows in banks.items():
  assert hashlib.sha256((DATA/(name+'.jsonl')).read_bytes()).hexdigest()==manifest['files'][name+'.jsonl']['sha256']
  assert len({t['id'] for t in rows})==len(rows)
 summary={'source_files':manifest['files'],'method':'Exact indexed geometry ignores round order and preferences; not permutation invariant; shared geometry is not automatically leaked answers. Selection uses no model success scores.','banks':{},'overlap':{}}
 for name,rows in banks.items():
  sp=name.startswith('selfplay');s={'count':len(rows),'geometry_count':len({geometry(t,sp) for t in rows})}
  if sp:
   s.update(players=count(t['players'] for t in rows),rounds=count(t['rounds'] for t in rows),prior_values=count(stable(t['raw']['preference_generation']['values']) for t in rows),completion=count('binary' if all(g['binary'] for g in t['raw']['game']['goals']) else 'linear' if not any(g['binary'] for g in t['raw']['game']['goals']) else 'mixed' for t in rows),nonempty_history=sum(bool(t['raw'].get('history')) for t in rows),negative_worlds=sum(any(v<0 for r in t['realized_world'] for v in r) for t in rows))
  else:
   b=[t for t in rows if t['task']=='B'];p=[t for t in rows if t['task']=='P']
   s.update(pools=count(t['pool'] for t in rows),sources=count(t['training_source'] for t in rows),families=len({t['family'] for t in rows}),largest_families=C.Counter(t['family'] for t in rows).most_common(5),B_gold=count(stable(t['teacher']['gold']) for t in b),B_fullset=sum(len(t['teacher']['gold']['possible_preferences'])==3 for t in b),B_fullset_undetermined=sum(len(t['teacher']['gold']['possible_preferences'])==3 and t['teacher']['gold']['favored']=='undetermined' for t in b),B_by_pool={k:{'count':len(v),'fullset':sum(len(t['teacher']['gold']['possible_preferences'])==3 for t in v),'sources':count(t['training_source'] for t in v)} for k in ('formation','update','maintain') if (v:=[t for t in b if t['pool']==k])},P_actions=count(stable(sorted({a['action'] for a in t['teacher']['acceptable_actions']})) for t in p),P_information=count(any(a['action']=='INVESTIGATE' for a in t['teacher']['acceptable_actions']) for t in p if t['pool']=='information'),B_history_lengths=count(len(t['input'].get('voluntary_history',[])) for t in b),binary_goals=count(g['binary'] for t in rows for g in t['input']['game']['goals']))
  summary['banks'][name]=s
 for kind in ('bp','selfplay'):
  a,b=(banks[kind+'_'+split] for split in ('train','validation'));sp=kind=='selfplay'
  keys={'id':lambda t:t['id'],'geometry':lambda t:geometry(t,sp),'exact_input':lambda t:sha([t['raw'],t['realized_world']]) if sp else sha(t['input'])}
  if not sp:keys.update(family=lambda t:t['family'],semantic_id=lambda t:t.get('semantic_id'))
  summary['overlap'][kind]={k:sorted(({fn(t) for t in a}&{fn(t) for t in b})-{None}) for k,fn in keys.items()}
 selected=[]
 for split in ('train','validation'):
  rows=banks['bp_'+split]
  for kind in ('B','P'):
   pool=[t for t in rows if t['task']==kind];n=8 if split=='train' else 4
   required=[]
   if kind=='B':
    required=[t for t in pool if t['training_source']=='l0']
    if split=='validation':required=required[:1]
    for skill in ('formation','update','maintain'):
     if not any(t['pool']==skill for t in required):required+=select([t for t in pool if t['pool']==skill],1)
   else:
    for skill in ('complete','uncertain','result_use','information'):
     choices=[t for t in pool if t['pool']==skill]
     if skill=='information' and split=='train':
      for positive in (False,True):required+=select([t for t in choices if bool(t.get('information_positive'))==positive],1)
     else:required.extend(select(choices,1 if split=='validation' else 2))
   selected.extend(select(pool,n,required=required))
 sp_selected=[]
 for split,n in [('train',8),('validation',4)]:sp_selected+=select(banks['selfplay_'+split],n,True)
 for name,rows in [('bp',selected),('selfplay',sp_selected)]:
  (OUT/(name+'_selected.jsonl')).write_text(''.join(json.dumps(t,ensure_ascii=False)+'\n' for t in rows))
 summary['B_sampler_expectations']={name:sum(weight*sum(predicate(t) for t in banks['bp_train'] if t['task']=='B' and t['pool']==pool)/sum(t['task']=='B' and t['pool']==pool for t in banks['bp_train']) for pool,weight in [('formation',.25),('update',.5),('maintain',.25)]) for name,predicate in {'l0_fraction':lambda t:t['training_source']=='l0','bridge_fraction':lambda t:t['training_source']=='bridge','fullset_undetermined_fraction':lambda t:len(t['teacher']['gold']['possible_preferences'])==3 and t['teacher']['gold']['favored']=='undetermined'}.items()}
 summary['selection']={'bp':[{k:t[k] for k in ('id','split','task','pool','training_source','family')} for t in selected],'selfplay':[{k:t.get(k) for k in ('id','split','players','rounds','level')} for t in sp_selected],'bp_repeats':8,'selfplay_repeats':4,'bp_calls':192,'full_games':48,'purpose':'Development diagnostic, not an unbiased accuracy estimate; validation never used to construct training replacements.'}
 (OUT/'audit.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({k:v for k,v in summary.items() if k in ('banks','overlap')},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
