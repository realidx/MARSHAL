import tarfile,json,hashlib,collections
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).parent
archive=ROOT/'new/team_benac_234_results_20260926/raw_runs.tar.gz'
runs={}
with tarfile.open(archive) as t:
 members={m.name:m for m in t.getmembers()}
 def read(n):return json.load(t.extractfile(n))
 for name in members:
  if not name.endswith('/summary.json'):continue
  base=name.rsplit('/',1)[0];model=base.split('/')[2].split('-4096-')[0];size=3 if base.endswith('/evaluation') else int(base[-1])
  rows=read(base+'/results.json');summary=read(name);protocol=read(base+'/protocol.json')
  games={};counts=collections.Counter();lengths=[]
  for r in rows:
   case=r['case_id'];path=base+'/'+case+'-r0-shared-q0'
   calls=[json.loads(l) for l in t.extractfile(path+'/calls.jsonl')];seats=read(path+'/results.json')
   actions=collections.Counter((c['action'].get('action',c['action'].get('response')) if c.get('valid') else 'INVALID') for c in calls)
   counts.update(actions)
   for c in calls:
    if c.get('usage'):lengths.append(c['usage'].get('completion_tokens',0))
   games[case]=dict(result=r,seats=seats,actions=dict(actions),calls=calls)
  runs[size,model]=dict(games=games,summary=summary,protocol=protocol,actions=dict(counts),mean_completion_tokens=sum(lengths)/len(lengths))
 compact={}
 for (size,model),run in runs.items():
  q0=runs[size,'q0'];pairs=[]
  for case,g in run['games'].items():
   a=g['result'];b=q0['games'][case]['result']
   if a['status']=='terminal' and b['status']=='terminal':pairs.append(dict(case=case,delta=a['total_utility']-b['total_utility']))
  compact[f'{size}/{model}']=dict(summary=run['summary'],actions=run['actions'],mean_completion_tokens=run['mean_completion_tokens'],q0_pairs=pairs,win=sum(x['delta']>1e-8 for x in pairs),tie=sum(abs(x['delta'])<=1e-8 for x in pairs),loss=sum(x['delta']< -1e-8 for x in pairs))
 (OUT/'metrics.json').write_text(json.dumps(compact,indent=2))
 (OUT/'games.json').write_text(json.dumps({f'{n}/{m}':{c:{k:v for k,v in g.items() if k!='calls'} for c,g in r['games'].items()} for (n,m),r in runs.items()},indent=2))
 for n in (2,3,4):
  print('\nPLAYERS',n)
  for m in ('q0','bpold99','sp41','o99','d39','micro24-39'):
   r=compact[f'{n}/{m}'];s=r['summary'];print(m,'bounds',s['all/all']['full_cohort_team_bounds'],'binary',round(s['all/binary']['conditional_team_utility'],3),'linear',round(s['all/linear']['conditional_team_utility'],3),'W/T/L',r['win'],r['tie'],r['loss'],'actions',r['actions'],'length',round(r['mean_completion_tokens']))
 # Candidate examples: largest paired gains/losses with complete trajectories.
 for n,m in [(3,'bpold99'),(4,'o99'),(3,'d39'),(4,'micro24-39')]:
  pairs=compact[f'{n}/{m}']['q0_pairs'];cases=sorted(pairs,key=lambda x:x['delta'])
  print('\nEXAMPLES',n,m,cases[:2],cases[-2:])
  for p in cases[:2]+cases[-2:]:
   c=p['case'];example={model:runs[n,model]['games'][c] for model in ('q0',m)}
   (OUT/f'example_{n}_{m}_{c}.json').write_text(json.dumps(example,indent=2))
 print('protocol tokens',[(n,m,r['protocol'].get('max_tokens'),r['protocol'].get('suite',{}).get('max_tokens')) for (n,m),r in runs.items()])
extra={}
for (n,m),run in runs.items():
 c=collections.Counter()
 for g in run['games'].values():
  cs=g['calls'];firsts={}
  for call in cs:
   if not call['valid']:continue
   ob=call['observation'];a=call['action'];name=a.get('action',a.get('response'));state=ob['public_state']
   if 'action' in a:firsts.setdefault(call['player'],name)
   if name=='INVESTIGATE' and state['turn_index']==len(ob['game']['round_robin'])-1:c['last_global_turn_investigations']+=1
  c['first_proposal_investigations']+=sum(v=='INVESTIGATE' for v in firsts.values());c['player_games']+=len(firsts)
  if g['result']['status']!='terminal':continue
  u=g['result']['utilities'];c['negative_payoff_seats']+=sum(v< -1e-9 for v in u);c['positive_team_games']+=sum(u)>1e-9
  c['pareto_vs_zero_games']+=all(v>= -1e-9 for v in u) and any(v>1e-9 for v in u)
  bits=g['seats'][0]['last_commitments'];goals=cs[0]['observation']['game']['goals']
  c['fully_achieved_goals']+=sum(all(bits[a['player_id']][a['action_id']] for a in goal['required_actions']) for goal in goals)
 extra[f'{n}/{m}']=dict(c)
print('\nBEHAVIOR',json.dumps(extra,indent=2))
(OUT/'behavior.json').write_text(json.dumps(extra,indent=2))
for n in (2,3,4):
 ms=[r['protocol']['suite']['files'] for (nn,m),r in runs.items() if nn==n];assert all(x==ms[0] for x in ms)
for m in ('q0','bpold99','sp41','o99','d39','micro24-39'):
 assert len({runs[n,m]['protocol']['checkpoint_hash'] for n in (2,3,4)})==1
print('Verified within-size suite file hashes and across-size checkpoint identities.')
