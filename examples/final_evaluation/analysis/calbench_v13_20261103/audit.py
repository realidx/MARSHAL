from pathlib import Path
from collections import Counter,defaultdict
import json,statistics,hashlib
ROOT=Path(__file__).resolve().parents[4];O=Path(__file__).resolve().parent;D=ROOT/'examples/final_evaluation/calbench_diagnostic_data/20261102'
RUNS={'Q-native':D/'qwen_base_prompt_1059395','O-native':D/'outcome99_base_prompt_872963','Q-belief':ROOT/'runs/calbench_soc/qwen4b_belief_v13_r2-stream-1065394','O-belief':ROOT/'runs/calbench_soc/outcome99_belief_v13_r2-stream-1065395','Q-inline':ROOT/'runs/calbench_soc/qwen4b_inline_v13_r2-stream-1065396','O-inline':ROOT/'runs/calbench_soc/outcome99_inline_v13_r2-stream-1065397'}
def read(p):return json.loads(p.read_text())
def lines(p):return list(map(json.loads,p.read_text().splitlines()))
def weights(p):return {k:v['sha256'] for k,v in read(p/'execution_identity.json')['files'].items() if k.endswith('.safetensors')}
allcases={};out={'runs':{},'pairs':{},'failures':[],'contracts':{},'identity':{},'initial':[]};examples=[]
for name,run in RUNS.items():
 cases={};cnt=Counter();tot=Counter();lengths=defaultdict(list);retrycounter=Counter();contract=Counter();maxctx=0
 for rp in sorted((run/'games').glob('*/result.json')):
  p=rp.parent;r=read(rp);ev=lines(p/'events.jsonl');acts={};mss={};rejections=[]
  for f in p.glob('transport-*.jsonl'):acts[int(f.stem.split('-')[-1])]=lines(f)
  for f in (p/'ms').glob('transport-*.jsonl'):mss[int(f.stem.split('-')[-1])]=lines(f)
  c=dict(result=r,events=ev,acts=acts,mss=mss,path=p,scenario=read(p/'scenario.json'));cases[p.name]=c
  starts={(e['data']['round'],e['data']['turn'],e['data']['agent_id']):e['data'] for e in ev if e['type']=='turn_start'}
  ends={(e['data'].get('raw_api_response') or {}).get('id'):e['data'] for e in ev if e['type']=='turn_end'}
  for aid,cs in acts.items():
   acceptedms={x['call_index']:x for x in mss.get(aid,[]) if x.get('accepted',True)}
   for x in cs:
    if not x.get('accepted',True):continue
    msgs=x['request']['messages'];last=msgs[-1]['content']
    if name.endswith('belief'):
     m=acceptedms[x['call_index']];assert msgs[:-2]==m['request']['messages'];assert msgs[-2]['content']==m['response']['choices'][0]['message']['content'];contract['shared_prefix_pairs']+=1
     assert x['request']['max_tokens']+m['response']['usage']['completion_tokens']==4096;contract['shared_budget_pairs']+=1
     current=msgs[-4]['content']
     end=ends.get(x['response'].get('id'))
     if end:
      start=starts[end['round'],end['turn'],end['agent_id']]
      for received in start.get('inbox_drained',[]):
       assert received['content'] in m['request']['messages'][-2]['content']
       contract['delivered_messages_visible_before_MS']+=1
     if current.startswith('[RETRY'):
      # Voluntary and decision retries carry different valid actions.
      if '=== DECISION PHASE ===' in last:
       contract['decision_retry_calls']+=1
       assert 'No messages may be sent during this phase' in last and '"actions" must contain at least one "schedule" tool call for meeting' in last
       contract['complete_decision_retry_contract']+=1
    else:current=last
    if current.startswith('[RETRY'):
     retrycounter['retry_calls']+=1
     try:obj=json.loads(x['response']['choices'][0]['message']['content'])
     except (ValueError,TypeError):retrycounter['unparsed']+=1;continue
     types=[a.get('type') for a in obj.get('actions',[])];retrycounter['DM_on_retry']+='dm' in types;retrycounter['retry_without_schedule']+='schedule' not in types
  for stage,groups in [('action',acts),('ms',mss)]:
   for aid,cs in groups.items():
    for x in cs:
     cnt[stage+'_physical_calls']+=1;response=x.get('response') or {};u=response.get('usage') or {}
     for k in ['prompt_tokens','completion_tokens']:tot[k]+=u.get(k,0)
     if u:lengths[stage].append(u['completion_tokens']);maxctx=max(maxctx,u['prompt_tokens']+x['request']['max_tokens'])
     if not x.get('accepted',True):
      text=(response.get('choices') or [{}])[0].get('message',{}).get('content','');out['failures'].append(dict(run=name,case=p.name,agent=aid,stage=stage,index=x['call_index'],attempt=x.get('prompt_attempt'),finish=(response.get('choices') or [{}])[0].get('finish_reason'),phase=('retry' if x['request']['messages'][-1]['content'].startswith('[RETRY') else 'decision' if x['request']['messages'][-1]['content'].startswith('=== DECISION') else 'cheap_talk') if stage=='action' and name.endswith('inline') else 'see_request',tokens=u.get('completion_tokens'),cap=x['request']['max_tokens'],chars=len(text),text_sha256=hashlib.sha256(text.encode()).hexdigest(),head=text[:450],tail=text[-900:],path=str((p/('ms' if stage=='ms' else '')/f'transport-agent-{aid}.jsonl').relative_to(ROOT))))
  if not r['engine_finished']:continue
  cnt['finished']+=1;cnt['valid']+=r['diagnostics']['final_valid_meetings'];cnt['full']+=r['coordinated_success'];cnt['semantic']+=r['diagnostics']['semantic_invalid_actions'];cnt['cost']+=r['metrics']['realized_cost'];cnt['dms']+=r['metrics']['total_dms_sent'];cnt['strict']+=r['strict_envelope_failures']
  for e in ev:
   if e['type']=='resolution':
    v=e['data'];cnt['round_success' if v['coordinated'] else 'failed_missing' if None in v['per_agent_slot'].values() else 'failed_disagreement']+=1
  for k,v in r['diagnostics']['invalid_action_reasons']['semantic'].items():
   group='missing_schedule' if 'exactly 1 schedule' in k else 'target_collision' if 'Two or more' in k else 'wrong_item' if 'claims item_id' in k else 'occupied_target' if 'occupied' in k else k
   cnt['error_'+group]+=v
 allcases[name]=cases;out['runs'][name]=dict(counts=dict(cnt),physical_tokens=dict(tot),generation_lengths={k:dict(mean=round(statistics.mean(v),2),median=statistics.median(v),max=max(v)) for k,v in lengths.items()},retry_stats=dict(retrycounter),max_prompt_plus_cap=maxctx,missing=[c for c,x in cases.items() if not x['result']['engine_finished']]);out['contracts'][name]=dict(contract)
for model in ['Q','O']:
 base=RUNS[model+'-native'];out['identity'][model]={n:dict(model_weight_sha256_equal=weights(base)==weights(RUNS[model+'-'+n]),scenarios_equal=all(allcases[model+'-native'][c]['scenario']==x['scenario'] for c,x in allcases[model+'-'+n].items())) for n in ['belief','inline']}
 for a,b in [('native','belief'),('native','inline'),('belief','inline')]:
  na,nb=model+'-'+a,model+'-'+b;cs=[c for c in allcases[na] if allcases[na][c]['result']['engine_finished'] and allcases[nb][c]['result']['engine_finished']];rows=[]
  for c in cs:
   ar,br=allcases[na][c]['result'],allcases[nb][c]['result'];rows.append(dict(case=c,a=ar['diagnostics']['final_valid_meetings'],b=br['diagnostics']['final_valid_meetings'],a_semantic=ar['diagnostics']['semantic_invalid_actions'],b_semantic=br['diagnostics']['semantic_invalid_actions']))
  out['pairs'][na+' -> '+nb]=dict(cases=len(cs),valid_a=sum(x['a'] for x in rows),valid_b=sum(x['b'] for x in rows),wins=sum(x['b']>x['a'] for x in rows),losses=sum(x['b']<x['a'] for x in rows),ties=sum(x['b']==x['a'] for x in rows),rows=rows)
 cs=[c for c in allcases[model+'-native'] if all(allcases[model+'-'+m][c]['result']['engine_finished'] for m in ['native','belief','inline'])]
 out['pairs'][model+' common_three']=dict(cases=cs,results={m:dict(valid=sum(allcases[model+'-'+m][c]['result']['diagnostics']['final_valid_meetings'] for c in cs),semantic=sum(allcases[model+'-'+m][c]['result']['diagnostics']['semantic_invalid_actions'] for c in cs),full=sum(allcases[model+'-'+m][c]['result']['coordinated_success'] for c in cs)) for m in ['native','belief','inline']})
# First player before any other player has acted: exactly same visible state.
for model in ['Q','O']:
 for case in allcases[model+'-native']:
  entries={}
  for mode in ['native','belief','inline']:
   c=allcases[model+'-'+mode][case];start=next(e['data'] for e in c['events'] if e['type']=='turn_start');aid=start['agent_id'];action=c['acts'][aid][0];entries[mode]=dict(action=action,belief=c['mss'][aid][0] if mode=='belief' else None)
  native=entries['native']['action']['request']['messages'];inline=entries['inline']['action']['request']['messages'];instruction=read(RUNS[model+'-inline']/'pipeline_snapshot.json')['contract']['inline_instruction'];assert inline[:-1]==native[:-1] and inline[-1]['content']==native[-1]['content']+'\n\n'+instruction
  out['initial'].append(dict(model=model,case=case,native_text=entries['native']['action']['response']['choices'][0]['message']['content'],inline_text=entries['inline']['action']['response']['choices'][0]['message']['content'],belief_text=entries['belief']['belief']['response']['choices'][0]['message']['content'],belief_action=entries['belief']['action']['response']['choices'][0]['message']['content']))
for mode in ['belief','inline']:
 cs=[c for c in allcases['Q-'+mode] if allcases['Q-'+mode][c]['result']['engine_finished'] and allcases['O-'+mode][c]['result']['engine_finished']]
 out['pairs']['model_comparison_'+mode]=dict(cases=cs,results={m:sum(allcases[m+'-'+mode][c]['result']['diagnostics']['final_valid_meetings'] for c in cs) for m in ['Q','O']})
for name,v in out['runs'].items():
 if not name.endswith('native'):
  v['all24_final_valid_bounds']=[v['counts']['valid'],v['counts']['valid']+3*(24-v['counts']['finished'])]
out['historical_inventory']={}
for run in sorted((ROOT/'runs/calbench_soc').iterdir()):
 if 'v13' in run.name or not run.is_dir():continue
 rs=[read(p) for p in sorted(run.glob('games/*/result.json'))]
 out['historical_inventory'][run.name]=dict(cases=len(rs),finished=sum(r['engine_finished'] for r in rs),
  scheduled=sum((r.get('metrics') or {}).get('meetings_scheduled',0) for r in rs),
  final_valid=(sum(r['diagnostics']['final_valid_meetings'] for r in rs)
    if rs and all('final_valid_meetings' in r.get('diagnostics',{}) for r in rs) else None),
  comparison='historical checkpoints/formal suites; excluded from v13 matched model comparisons')
inputs={}
for run in list(RUNS.values())+list((ROOT/'runs/calbench_soc').iterdir()):
 if not run.is_dir():continue
 for p in run.rglob('*'):
  if p.is_file() and (p.name in ('pipeline_snapshot.json','execution_identity.json','result.json','scenario.json','events.jsonl') or p.name.startswith('transport-agent-')):
   inputs[str(p.relative_to(ROOT))]=dict(sha256=hashlib.sha256(p.read_bytes()).hexdigest(),bytes=p.stat().st_size)
out['version12_paired']={}
for model,dirname in [('Q','qwen_base_1063524'),('O','outcome99_step99_1063527')]:
 saved={}
 for p in (D/'v12_inbox'/dirname/'games').glob('*/result.json'):
  saved[p.parent.name]=read(p)
  inputs[str(p.relative_to(ROOT))]=dict(sha256=hashlib.sha256(p.read_bytes()).hexdigest(),bytes=p.stat().st_size)
 cs=[c for c,r in saved.items() if r['engine_finished'] and allcases[model+'-belief'][c]['result']['engine_finished']]
 out['version12_paired'][model]=dict(cases=cs,v12_valid=sum(saved[c]['diagnostics']['final_valid_meetings'] for c in cs),v13_valid=sum(allcases[model+'-belief'][c]['result']['diagnostics']['final_valid_meetings'] for c in cs))
previous=ROOT/'examples/final_evaluation/calbench_diagnostic_data/20261102/v12_inbox/outcome99_step99_1063527/games/dense_uniform_s1/transport-agent-0.jsonl'
inputs[str(previous.relative_to(ROOT))]=dict(sha256=hashlib.sha256(previous.read_bytes()).hexdigest(),bytes=previous.stat().st_size)
(O/'INPUT_MANIFEST.json').write_text(json.dumps(inputs,sort_keys=True,indent=2)+'\n')
(O/'analysis.json').write_text(json.dumps(out,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
for n,v in out['runs'].items():print(n,json.dumps(v,ensure_ascii=False))
print('CONTRACTS',out['contracts']);print('IDENTITY',out['identity'])
for k,v in out['pairs'].items():print(k,json.dumps({k:x for k,x in v.items() if k!='rows'},ensure_ascii=False))
