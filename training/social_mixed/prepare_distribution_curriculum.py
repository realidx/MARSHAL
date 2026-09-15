"""Re-solve complete BP cores across public priors; preserve random full games."""
from collections import Counter,defaultdict
from copy import copy,deepcopy
from functools import lru_cache
from fractions import Fraction
from pathlib import Path
import hashlib,json
import numpy as np
from training.b_sft.preference_contract import VERSION,PROFILES,profile,belief,B_MARGIN
from training.b_sft.debug.audit_readable_pretraining import reconstruct
from training.b_sft.social_private_teacher import PrivateEpisode,audit_native
from training.b_sft.social_named_probe import request,present
from training.b_sft.social_bp_curriculum import acceptable
from training.b_sft.social_p_qualitative import robust_actions,WIDE_ENVELOPES
from training.b_sft.decision_policy import VERSION as POLICY
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'examples/social_mixed/data_distribution_v1'
SOURCE=ROOT/'examples/social_bp/p4_information_core_v1/bp_candidate_tasks.jsonl'
def read(p):return [json.loads(x) for x in p.read_text().splitlines()]
def stable(v):return json.dumps(v,sort_keys=True,separators=(',',':'))
def sha(v):return hashlib.sha256(v).hexdigest()
@lru_cache(maxsize=4)
def root_episode(key):
 raw,setup=json.loads(key);e=PrivateEpisode(raw,setup,seconds=45,max_nodes=80000,max_sweeps=128)
 return e,audit_native(e.tree)
def current_belief(e,i,facts):
 q=i['queries'][0];b=e.belief(q['player'],q['goal'],observer=i['player'],own=[{'want':1,'neutral':0,'avoid':-1}[i['own_preferences'][f'goal_{g}']] for g in range(len(i['game']['goals']))],private_results=facts)
 return belief(b['preference_weights']),b['preference_weights']
def transform(t,name,kernel):
 x=deepcopy(t);i=x['input'];prior=profile(name);i['background_prior']=prior;i['favored_margin']=B_MARGIN
 x.update(origin_id=t['id'],kernel=kernel,background_profile=name,contract_version=VERSION,objective_version=POLICY,training_ready=True)
 x['id']=sha(stable([VERSION,name,t['id']]).encode())[:20];x['native_task_id']=x['id']
 x['teacher']={};x['diagnostic_only']=False
 x['completion_mode']='binary' if all(g['binary'] for g in i['game']['goals']) else 'linear' if not any(g['binary'] for g in i['game']['goals']) else 'mixed'
 visible=present(t,t.get('name_variant',0));new=[r for r in visible['history'] if r.get('belief_period')=='new evidence']
 if t['task']=='B' and i.get('previous_belief')==t['teacher']['gold'] and new and all(r['actor']==visible['you'] and r.get('response') for r in new):
  mass=t['teacher']['preference_weights'];gold=belief(mass);i['previous_belief']=gold
  x['teacher']=dict(gold=gold,preference_weights=mass,objective_version=POLICY,proof='supplied_previous_belief_preserved_by_own_response',favored_margin=B_MARGIN)
 else:
  raw,own=reconstruct(i);raw['background_prior']=prior
  root,native=root_episode(stable([raw,i['imposed_setup']]));e=copy(root);e.weights=root.weights.copy()
  facts=[(f['player'],f['goal'],{'want':1,'neutral':0,'avoid':-1}[f['preference']]) for f in i['private_results']]
  events=i['voluntary_history'];boundary=len(events)-len(i.get('new_history',events[-1:]))
  for n,a in enumerate(events):
   if t['task']=='B' and 'previous_belief' in i and n==boundary:
    slots=__import__('training.b_sft.social_private_teacher',fromlist=['observed_slots']).observed_slots(e.tree.entries[e.index].node,i['player'])
    oldfacts=[f for f in facts if f[:2] in slots];i['previous_belief']=current_belief(e,i,oldfacts)[0]
   e.observe(a)
  teacher=dict(policy_sha256=e.tree.certificate['policy_sha256'],native=native,objective_version=POLICY,background_prior=prior)
  if t['task']=='B':
   gold,mass=current_belief(e,i,facts);teacher.update(gold=gold,preference_weights=mass,favored_margin=B_MARGIN)
  else:
   entry=e.tree.entries[e.index];actions=[a.to_dict() for a in entry.actions]
   if actions!=i['legal_actions']:raise ValueError('Changed legal action order')
   pay=np.array([e.tree.values[c] for c in entry.children]);weights=e._weights(i['player'],own,facts)
   supplied=i['supplied_belief'];joint=supplied.get('joint_distribution')
   if joint:
    weights=np.zeros(len(e.tree.worlds));known=supplied['known_preferences']
    for row in joint:
     ff=known+row['preferences'];ids=[j for j,w in enumerate(e.tree.worlds) if all(w[f['player']][f['goal']]=={'want':1,'neutral':0,'avoid':-1}[f['preference']] for f in ff)]
     if len(ids)!=1:raise ValueError('Incomplete explicit joint row')
     weights[ids[0]]+=float(Fraction(row['probability']))
    if not np.isclose(weights.sum(),1):raise ValueError('Joint probability mass')
   if 'qualitative' in i:
    cert=robust_actions(pay,i['player'],e.tree.worlds,t['teacher']['claims'],own_tolerance=.1,social_tolerance=.1,envelopes=WIDE_ENVELOPES,offer_response=entry.node.pending is not None)
    indices=cert['acceptable'];teacher.update(qualitative_certificate=cert,claims=t['teacher']['claims'],audit_envelopes=WIDE_ENVELOPES)
    i['qualitative_ranges']={c['level']:[min(v[0] for v in WIDE_ENVELOPES[c['level']]),max(v[1] for v in WIDE_ENVELOPES[c['level']])] for c in t['teacher']['claims']}
   else:
    values=np.einsum('awp,w->ap',pay,weights);indices=acceptable(values,i['player'],actions=actions);teacher['action_values']=values.tolist()
   if not indices:raise ValueError('No robust acceptable action')
   teacher.update(acceptable_actions=[actions[j] for j in indices],all_legal_accepted=len(indices)==len(actions),own_tolerance=.1,social_tolerance=.1,
     per_world_payoffs=pay.tolist(),worlds=e.tree.worlds)
   if len(indices)==len(actions):x.update(training_ready=False,diagnostic_only=True)
  x['teacher']=teacher
 x['answer_signature']=stable(x['teacher'].get('gold',x['teacher'].get('acceptable_actions')))
 # Task source names/group IDs never reach model messages.
 x['contrast_group']=f'{kernel}:{t.get("p123_case",t.get("p4_case",t.get("b3_case",t.get("b12_case",t.get("contrast_group",t["id"])))))}'
 return annotate(x)

def annotate(x):
 x['training_pack_version']=VERSION
 if x['task']=='B' and 'previous_belief' in x['input']:
  x['skill']=x['pool']='maintain' if x['input']['previous_belief']==x['teacher']['gold'] else 'update'
  x['input']['task']=x['skill']
 if x['task']=='P':
  actions=x['teacher']['acceptable_actions'];q=any(a.get('action')=='INVESTIGATE' for a in actions);ordinary=any(a.get('action')!='INVESTIGATE' for a in actions)
  x['information_role']='both' if q and ordinary else 'query_only' if q else 'ordinary_only'
  x['information_positive']=q and not ordinary
  x['information_negative_kind']=None if q else 'ordinary_action_preferred'
 x['semantic_id']=sha(stable([VERSION,x['task'],x['input']]).encode())
 return x

def selfplay():
 from training.social_mixed.frozen.benac_p.generator import GeneratorConfig,_sample_preferences
 from training.social_mixed.core import seed_for
 result={}
 for split,path in [('train','examples/social_mixed/selfplay_audit_v2/train_candidate.jsonl'),('validation','examples/social_mixed/data/selfplay_validation.jsonl')]:
  rows=[]
  for r in read(ROOT/path):
   for name in PROFILES:
    x=deepcopy(r);g=x['raw']['game'];pr=profile(name);weights=list(pr['weights'].values());probs=tuple(v/sum(weights) for v in weights)
    cfg=GeneratorConfig(n_players=g['n_players'],actions_per_player=max(g['n_actions_per_player']),n_goals=len(g['goals']),n_rounds=len(g['round_robin'])//g['n_players'],preference_probs=probs)
    seed=seed_for(20260916,'prior-redraw',r['id'],name);rng=np.random.default_rng(seed)
    for attempt in range(10000):
     world=_sample_preferences(rng,cfg)
     if world is not None:break
    else:raise ValueError('Preference generator exhausted')
    x['geometry_source_id']=r['id']
    if 'generation' in x:x['geometry_generation']=x.pop('generation')
    x.update(id=f'{r["id"]}:{name}',background_profile=name,realized_world=world.tolist(),preference_redraw=dict(seed=seed,attempt=attempt,probabilities=probs,source='native _sample_preferences; original random geometry; no outcome filtering'))
    x['raw']['preference_generation']=dict(version=VERSION,values=[-1,0,1],background_prior=pr)
    rows.append(x)
  result[split]=rows
 return result

def main():
 OUT.mkdir(exist_ok=True)
 assigns={r['id']:r for r in read(ROOT/'examples/social_bp/response_only_v1/kernels_v1/assignments.jsonl')}
 source=[t for t in read(SOURCE) if t['split']!='test' and not assigns.get(t['id'],{}).get('deferred')]
 source+=read(ROOT/'examples/social_bp/p4_information_core_v1/diagnostic_tasks.jsonl')
 source.sort(key=lambda t:stable([t['input']['game'],t['input']['public_preferences'],t['input']['imposed_setup']]))
 good=[];diagnostics=[];errors=[]
 # Stream records so long builds remain inspectable and recoverable.
 with (OUT/'build_progress.jsonl').open('w') as stream:
  for name in PROFILES:
   for t in source:
    k=t.get('kernel',assigns.get(t['id'],{}).get('kernel'))
    try:
     x=transform(t,name,k);(diagnostics if x['diagnostic_only'] else good).append(x)
     event=dict(id=t['id'],profile=name,status='diagnostic' if x['diagnostic_only'] else 'ok',kernel=k)
    except Exception as exc:
     event=dict(id=t['id'],split=t['split'],profile=name,kernel=k,error=type(exc).__name__+': '+str(exc));errors.append(event)
    stream.write(json.dumps(event)+'\n');stream.flush()
   print('PROFILE DONE',name,'approved',len(good),'diagnostic',len(diagnostics),'failed',len(errors),flush=True)
   root_episode.cache_clear()
 sp=selfplay();files={}
 def write(name,rows):
  data=''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows).encode();(OUT/name).write_bytes(data);files[name]=dict(count=len(rows),sha256=sha(data))
 for split in ('train','validation'):
  write('bp_'+split+'.jsonl',[t for t in good if t['split']==split]);write('selfplay_'+split+'.jsonl',sp[split])
 write('diagnostics.jsonl',diagnostics);write('build_errors.jsonl',errors)
 write('requests_train.jsonl',[dict(id=t['id'],request=request(t,'action_tools',t.get('name_variant',0))) for t in good if t['split']=='train'])
 sources=['training/b_sft/preference_contract.py','training/b_sft/review_prompt.py','training/b_sft/social_prompt.py','training/b_sft/social_named_probe.py','training/b_sft/social_private_teacher.py','training/b_sft/decision_policy.py','training/b_sft/social_p_qualitative.py','training/social_mixed/policy_prompt.py','training/social_mixed/weighted_rules.py','training/social_mixed/distribution_sampling.py','training/social_mixed/frozen/bp_display.py','training/social_mixed/frozen/selfplay_prompt.py']
 manifest=dict(version=VERSION,files=files,prompt_sources={n:sha((ROOT/n).read_bytes()) for n in sources},counts={split:dict(Counter(t['kernel'] for t in good if t['split']==split)) for split in ('train','validation')},errors=len(errors),b_margin=B_MARGIN,p_own_tolerance=.1,p_social_tolerance=.1,profiles={k:profile(k) for k in PROFILES},original_source_sha256=sha(SOURCE.read_bytes()),model_calls=0)
 (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');print('BUILD COMPLETE',json.dumps(manifest['counts']),flush=True)
if __name__=='__main__':main()
