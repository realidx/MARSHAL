"""Full-source inventory and certified-history seed bank; never relabel exogenous beliefs."""
from copy import deepcopy
from collections import Counter
import hashlib,json
from pathlib import Path
from training.b_sft.preference_contract import belief
from training.social_mixed.audit_zero_signal import interface_check
from training.social_mixed.paired_requests import request
ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'examples/social_mixed/data_reasoning_v6'
OUT=ROOT/'examples/social_mixed/paired_bank_v1'
def digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True).encode()).hexdigest()
def main():
 OUT.mkdir(exist_ok=True);inventory=[];bank=[];seen={}
 audit=OUT/"reconstruction.jsonl"
 rebuilt={r["source_sha256"]:r for r in map(json.loads,audit.read_text().splitlines())} if audit.exists() else {}
 for split in ('train','validation'):
  rows=[json.loads(l) for l in (SOURCE/f'bp_{split}.jsonl').read_text().splitlines()]
  for t in rows:
   original=deepcopy(t)
   reason='requires_native_reconstruction'
   if t.get('b_bridge'):reason='training_scaffold_excluded'
   elif t.get('oracle_pair_of'):reason='oracle_view_duplicate'
   elif t['task']=='B':reason='belief_question_requires_action_point'
   elif t['input'].get('belief_source')=='history':reason='candidate'
   record=dict(id=t['id'],split=split,status=reason,source_kernel=t['kernel'],source_skill=t.get('skill'),source_family=t.get('structure_family'),source_task=t['task'])
   from training.social_mixed.prepare_distribution_curriculum import stable
   source_sha=hashlib.sha256(stable(t).encode()).hexdigest()
   if reason in ('requires_native_reconstruction','belief_question_requires_action_point') and source_sha in rebuilt:
    result=rebuilt[source_sha];record['status']=result['status']
    if result['status']=='reconstructed':
     t=result['task'];reason='candidate';record['native_reconstructed']=True;record['state_repairs']=result.get('state_repairs',[]);record['own_query_interventions']=result.get('own_query_interventions',[])
   if reason=='candidate':
    teacher=t['teacher'];inp=t['input'];worlds=teacher['worlds'];weights=teacher['posterior']
    assert abs(sum(weights)-1)<1e-8 and min(weights)>=0 and teacher['policy_sha256']
    assert teacher['acceptable_actions'] and len(teacher['acceptable_actions'])<len(inp['legal_actions'])
    assert len(teacher['action_values'])==len(inp['legal_actions'])
    key=digest({k:v for k,v in inp.items() if k not in ('supplied_belief','belief_source')})
    if key in seen:
     record['canonical_id']=key
     record['status']='canonical_duplicate' if seen[key]==split else 'cross_split_duplicate_excluded'
    else:
     seen[key]=split
     options=[]
     for p in range(inp['game']['n_players']):
      if p==inp['player']:continue
      for g in range(len(inp['game']['goals'])):
       m={name:sum(w for world,w in zip(worlds,weights) if world[p][g]==val) for name,val in [('want',1),('neutral',0),('avoid',-1)]}
       options.append((1-max(m.values()),p,g,m))
     query=original['input'].get('queries',[]) if original['task']=='B' else []
     if len(query)==1:
      _,p,g,m=next(o for o in options if o[1:3]==(query[0]['player'],query[0]['goal']))
     else:
      _,p,g,m=max(options,key=lambda x:(x[0],-x[1],-x[2]))
     views=[]
     for view in ('O','B','Pplus'):
      x=deepcopy(t);x.update(id=key[:20]+'-'+view,canonical_id=key,paired_view=view,canonical_action_task=deepcopy(t),source_task_id=original['id'],source_kernel=original['kernel'])
      if view=='B':
       x.update(task='B',kernel='B1',skill='formation',pool='formation')
       if original['task']=='B':
        x.update(kernel=original['kernel'],skill=original['skill'],pool=original['pool'])
        for field in ('previous_belief','old_history','new_history'):
         if field in original['input']:x['input'][field]=deepcopy(original['input'][field])
       x['input']['queries']=[dict(player=p,goal=g)];x['input']['task']=x['skill']
       x['teacher']=dict(gold=belief(m),preference_weights=m,policy_sha256=teacher['policy_sha256'])
      elif view=='Pplus':
       names={1:'want',0:'neutral',-1:'avoid'}
       x['input']['supplied_belief']=dict(known_preferences=[],unresolved_preferences=[],support='Exact same-information joint posterior',joint_distribution=[dict(probability=str(float(w)),preferences=[dict(player=p,goal=g,preference=names[v]) for p,row in enumerate(world) for g,v in enumerate(row)]) for world,w in zip(worlds,weights) if w>0])
      views.append(x)
     for x in views:assert interface_check(x,request_builder=request)['all_passed']
     bank.extend(views);record.update(status='paired',canonical_id=key,b_query_uncertainty=1-max(m.values()))
   inventory.append(record)
 (OUT/'tasks.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in bank))
 (OUT/'inventory.json').write_text(json.dumps(inventory,indent=2))
 (OUT/'manifest.json').write_text(json.dumps(dict(version='paired-v1',counts=dict(Counter((r['split']+':'+r['status']) for r in inventory)),cases=len(bank)//3,source_sha256=hashlib.sha256((SOURCE/'manifest.json').read_bytes()).hexdigest(),source_files={f'bp_{split}.jsonl':hashlib.sha256((SOURCE/f'bp_{split}.jsonl').read_bytes()).hexdigest() for split in ('train','validation')},reconstruction_sha256=hashlib.sha256(audit.read_bytes()).hexdigest() if audit.exists() else None,tasks_sha256=hashlib.sha256((OUT/'tasks.jsonl').read_bytes()).hexdigest(),scoring='existing teacher-policy-consistent acceptable set; response altruism retained',limitation='Only certified actionable cases included; inventory records terminal, non-observer and unresolved cases. Not full-source coverage.'),indent=2))
 print((OUT/'manifest.json').read_text())
if __name__=='__main__':main()
