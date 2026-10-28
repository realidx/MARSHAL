"""Small scoring-mode contrasts; never label zero-likelihood observations."""
from copy import deepcopy
from collections import Counter
import hashlib,json
import numpy as np
from training.b_sft.build_b3_external import ROOT,fixture,label,local_policy_audit
from training.b_sft.prepare_no_catalogue_probe import expand_support
from training.b_sft.social_private_teacher import PrivateEpisode,audit_native
from training.b_sft.build_bp_pilot import make_task,topology
from training.b_sft.bp_semantics import semantic_id
from training.b_sft.decision_policy import VERSION
from training.b_sft.social_named_probe import request
from training.b_sft.social_bp_training import native_completion,reward
OUT=ROOT/'examples/social_bp/b12_linear_contrasts_v1'
CASES=[('B1','partial_helpful',[1,1],[0],[1,0]),
       ('B1','partial_harmful',[-1,1],[0],[1,0]),
       ('B1','compensated_control',[1,1],[1],[0,1]),
       ('B2','target_offer_control',[1,1],[1,0],[1]),
       ('B2','background_offer',[1,1],[0,1],[1]),
       ('B2','partial_background',[1,1],[0,1],[0])]

def build():
 bank=[json.loads(s) for s in (ROOT/'examples/social_bp/data_two_a100_v1/tasks.jsonl').read_text().splitlines()]
 train={t['family'] for t in bank if t['split']=='train'};held={t['family'] for t in bank if t['split']!='train'}
 tasks=[];checks=[];unavailable=[]
 for kernel,case,own,proposer,partner in CASES:
  for binary in (True,False):
   raw,_=fixture(2,binary);raw['own_preferences']=own;raw['type_catalogues']['0']=[own]
   raw['game']['round_robin']=[1,0] if kernel=='B1' else [0,1]
   raw,public,_=expand_support(raw);family=topology(raw)
   assert family in train and family not in held
   offer=dict(action='OFFER',partner_id=1 if kernel=='B1' else 0,proposer_action=proposer,partner_action=partner)
   setup=[dict(action='PASS')]+([offer] if kernel=='B1' else [])
   observations=[dict(response=r) for r in ('ACCEPT','REJECT')] if kernel=='B1' else [offer]
   for observation in observations:
    e=PrivateEpisode(raw,setup,seconds=30,max_nodes=60000)
    audit=audit_native(e.tree);policy_checks=local_policy_audit(e.tree)
    entry=e.tree.entries[0];ai=[a.to_dict() for a in entry.actions].index(observation)
    prior=e._weights(0,own,[]);lik=e.tree.policy[0][ai];posterior=prior*lik
    rec=dict(kernel=kernel,case=case,mode='binary' if binary else 'linear',observation=observation,likelihood=lik.tolist())
    if not posterior.sum():unavailable.append(rec);continue
    posterior/=posterior.sum();gold,mass=label(posterior,e.tree.worlds,0)
    e.observe(observation);np.testing.assert_allclose(posterior,e._weights(0,own,[]),atol=1e-9,rtol=0)
    t=make_task(e,public,setup,[observation],'B',1,family,source='b12-linear-v1:'+case+':'+rec['mode'])
    assert t['teacher']['gold']==gold
    t.update(split='train',training_ready=False,objective_version=VERSION,kernel=kernel,
             completion_mode=rec['mode'],b12_case=case,short_teaching=True)
    t['semantic_id']=semantic_id(t)
    alternatives=[dict(action=a.to_dict(),likelihood=e.tree.policy[0][i].tolist()) for i,a in enumerate(entry.actions)]
    t['teacher']['b12_audit']=dict(native=audit,information_set_checks=policy_checks,
       worlds=e.tree.worlds,prior=prior.tolist(),likelihood=lik.tolist(),posterior=posterior.tolist(),alternatives=alternatives)
    assert reward(t,native_completion(t))['reward']==1
    tasks.append(t);checks.append(dict(rec,id=t['id'],gold=gold,marginal=mass))
 return tasks,checks,unavailable

def main():
 tasks,checks,unavailable=build();OUT.mkdir(parents=True,exist_ok=True)
 requests=[dict(task_id=t['id'],condition='b12-linear-v1',request=request(t,'action_tools',t['name_variant'])) for t in tasks]
 previous=[json.loads(s) for s in (ROOT/'examples/social_bp/b3_external_linear_v1/bp_candidate_tasks.jsonl').read_text().splitlines()]
 seen={semantic_id(t) for t in previous};candidate=previous.copy();reused=[]
 for t in tasks:
  if t['semantic_id'] in seen:reused.append(t['id'])
  else:candidate.append(t);seen.add(t['semantic_id'])
 files={}
 for name,rows in [('tasks.jsonl',tasks),('requests.jsonl',requests),('bp_candidate_tasks.jsonl',candidate)]:
  data=''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows).encode();(OUT/name).write_bytes(data);files[name]=hashlib.sha256(data).hexdigest()
 manifest=dict(version='b12-linear-contrasts-v1',tasks=len(tasks),counts=dict(Counter(t['kernel']+'_'+t['completion_mode'] for t in tasks)),
   checks=checks,zero_likelihood_excluded=unavailable,reused_semantics=reused,candidate_tasks=len(candidate),
   candidate_B_train=sum(t['task']=='B' and t['split']=='train' for t in candidate),
   training_ready=False,model_tested=False,merged=False,test_used=False,files=files)
 (OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
 cards=['# B1/B2 binary–linear 对照','']
 for t,r in zip(tasks,requests):
  cards += [f"## {t['kernel']} {t['b12_case']} {t['completion_mode']} {t['input']['voluntary_history'][-1]}",'',r['request']['messages'][1]['content'],'','审核标签（不发给模型）：'+json.dumps(t['teacher']['gold'],ensure_ascii=False),'']
 (OUT/'cards.md').write_text('\n'.join(cards)+'\n')
 print(json.dumps({k:v for k,v in manifest.items() if k not in ('files','checks','zero_likelihood_excluded')},ensure_ascii=False))
 print(json.dumps(checks,ensure_ascii=False))
if __name__=='__main__':main()
