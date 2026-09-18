"""Read-only native replay and paired analysis of downloaded package A results."""
import json,hashlib,statistics
from collections import Counter,defaultdict
from pathlib import Path
from training.social_mixed.core import Episode,sp_prompt
from examples.final_evaluation.benac_a_suite import SEED,load
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).parent
paths={'q0':'q0-formal-859851','sp':'selfplay-step69-formal-859921','bp':'bp-step139-formal-859921','mixed':'mixed-step59-formal-859921'}
manifest,frozen=load();byid={r['id']:r for r in frozen};results={};audits={};identities={};evidence=[]
def key(r):return r['reset']['id']+':'+str(r['focal_seat'])
def average(xs):return sum(xs)/len(xs) if xs else None
for model,name in paths.items():
 p=ROOT/'runs/benac_a_soc'/name
 rows=[json.loads(l) for l in (p/'games/games.jsonl').read_text().splitlines()];results[model]={key(r):r for r in rows}
 identities[model]=json.loads((p/'execution_identity.json').read_text())
 protocol=json.loads((p/'games/protocol.json').read_text());assert protocol['suite']==manifest
 assert len(rows)==48 and len(results[model])==48 and (p/'EXIT_CODE').read_text().strip()=='0'
 assert json.loads((p/'games/RUN_FINISHED.json').read_text())['recorded']==48
 counts=Counter();errors=Counter();tokens=[];reasonchars=[];strata={};endroles=Counter();action_counts=Counter();initial_requests={};examples=[]
 for r in rows:
  assert r['reset']==byid[r['reset']['id']]
  d=p/'games'/f'{r["reset"]["id"]}-seat{r["focal_seat"]}'
  assert json.loads((d/'result.json').read_text())==r
  calls=[json.loads(l) for l in (d/'calls.jsonl').read_text().splitlines()]
  ep=Episode(r['reset'],r['reset']['id'],0,SEED)
  for line,c in enumerate(calls,1):
   actor=ep.rules.actor(ep.node);role='focal' if actor==r['focal_seat'] else 'q0'
   assert c['role']==role and c['player']==actor and c['observation']==ep.observation()
   req=ep.request();assert all(c['request'][k]==req[k] for k in ('messages','tools','seed'))
   assert (c['request']['temperature'],c['request']['max_tokens'],c['request']['top_p'])==(1.0,1024,1.0)
   assert c['request']['model']==f'benac-{role}'
   if line==1:initial_requests[key(r)]=req
   counts[role+'_calls']+=1;counts[role+'_invalid']+=not c['valid'];counts[role+'_truncated']+=c['completion']['finish_reason']=='length'
   if role=='focal':
    tokens.append(c['usage']['completion_tokens']);content=c['completion']['raw_message'].get('content') or '';reasonchars.append(len(content))
    if c['valid']:
     a=c['action'];action_counts[a.get('action',a.get('response','unknown'))]+=1
     if a.get('action') in ('INVESTIGATE','PASS','OFFER'):
      counts['valid_proposal_decisions']+=1
      if a['action']=='INVESTIGATE':counts['investigate_last_global_opportunity']+=ep.node.state.turn_index==len(ep.rules.spec.round_robin)-1
    elif c['completion']['finish_reason']=='length':errors['truncated']+=1
    else:
     raw=c['completion']['raw_message'];tc=raw.get('tool_calls') or []
     reason='not_exactly_one_tool'
     if len(tc)==1:
      f=tc[0]['function']
      try:
       a=sp_prompt.decode_call(ep.observation(),f['name'],json.loads(f['arguments']))
       legal={json.dumps(x.to_dict(),sort_keys=True) for x in ep.rules.actions(ep.node)}
       reason='native_illegal_action' if json.dumps(a,sort_keys=True) not in legal else 'unexplained'
      except Exception as exc:reason=type(exc).__name__+': '+str(exc)
     errors[reason]+=1
     ex=dict(model=model,game=key(r),line=line,path=str((d/'calls.jsonl').relative_to(ROOT)),reason=reason,raw=raw,observation=c['observation'])
     examples.append(ex)
   ep.accept(c)
   assert ep.calls[-1]['valid']==c['valid']
  assert ep.status==r['status'] and ep.terminal==r['terminal_utility'] and ep.penalties==r['protocol']
  if ep.status!='terminal':endroles[calls[-1]['role']]+=1
 for split in ('all','ID','OOD'):
  for mode in ('all','binary','linear'):
   group=[r for r in rows if (split=='all' or r['split']==split) and (mode=='all' or r['mode']==mode)];done=[r for r in group if r['status']=='terminal']
   strata[split+'/'+mode]=dict(n=len(group),completed=len(done),utility=average([r['focal_utility'] for r in done]),team=average([r['total_utility'] for r in done]),bounds=[sum(r['focal_utility'] if r['status']=='terminal' else r['missing_utility_bounds'][i] for r in group)/len(group) for i in (0,1)])
 audits[model]=dict(counts=dict(counts),actions=dict(action_counts),errors=dict(errors),failure_actor=dict(endroles),mean_tokens=average(tokens),median_tokens=statistics.median(tokens),total_tokens=sum(tokens),mean_reasoning_chars=average(reasonchars),strata=strata)
 evidence+=examples
 # Initial observations across arms are independent of endpoint/model.
 if model=='q0':base_requests=initial_requests
 else:assert initial_requests==base_requests
for model in identities:
 assert identities[model]['q0']['files']==identities['q0']['q0']['files']
 assert identities[model]['versions']==identities['q0']['versions']
 assert identities[model]['evaluation_scripts']==identities['q0']['evaluation_scripts']
assert identities['q0']['focal']['files']==identities['q0']['q0']['files']
paired={}
for a,b in [('sp','q0'),('bp','q0'),('mixed','q0'),('mixed','sp'),('mixed','bp')]:
 paired[a+'-'+b]={}
 for split in ('all','ID','OOD'):
  keys=[k for k,r in results[a].items() if split=='all' or r['split']==split]
  common=[k for k in keys if results[a][k]['status']==results[b][k]['status']=='terminal']
  diffs=[results[a][k]['focal_utility']-results[b][k]['focal_utility'] for k in common]
  paired[a+'-'+b][split]=dict(common_terminal=len(common),mean_difference=average(diffs),wins=sum(d>1e-9 for d in diffs),ties=sum(abs(d)<1e-9 for d in diffs),losses=sum(d< -1e-9 for d in diffs),a_only_complete=sum(results[a][k]['status']=='terminal' and results[b][k]['status']!='terminal' for k in keys),b_only_complete=sum(results[b][k]['status']=='terminal' and results[a][k]['status']!='terminal' for k in keys))
allcommon=[k for k in results['q0'] if all(results[m][k]['status']=='terminal' for m in paths)]
report=dict(validation='192 episodes replayed against frozen native rules; all summaries, source manifests, initial requests and shared Q0 hashes consistent',models=audits,paired=paired,all_four_complete=dict(count=len(allcommon),means={m:average([results[m][k]['focal_utility'] for k in allcommon]) for m in paths}),limitations='One rollout per seat. ID spans 3 geometries; OOD 8. Missingness is policy-dependent; survivor means and common-terminal pairs are diagnostic only. No independent-seat significance test.')
(OUT/'summary.json').write_text(json.dumps(report,indent=2)+'\n');(OUT/'invalid_call_evidence.json').write_text(json.dumps(evidence,indent=2)+'\n')
print(json.dumps(report,indent=2))
