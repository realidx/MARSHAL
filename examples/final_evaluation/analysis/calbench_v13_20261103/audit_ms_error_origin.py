"""Extract saved MS/ACTION pairs and explicit human annotations; no inference."""
from pathlib import Path
import json
import hashlib
R=Path(__file__).resolve().parents[4];records=[]
for model,name in [('Q','qwen4b_belief_v13_r2-stream-1065394'),('O','outcome99_belief_v13_r2-stream-1065395')]:
 for p in sorted((R/'runs/calbench_soc'/name/'games').iterdir()):
  if not p.is_dir():continue
  ev=list(map(json.loads,(p/'events.jsonl').read_text().splitlines()));actions={};ms={}
  for f in p.glob('transport-*.jsonl'):
   aid=int(f.stem.split('-')[-1]);actions[aid]={c.get('response',{}).get('id'):c for c in map(json.loads,f.read_text().splitlines()) if c.get('accepted')}
  for f in (p/'ms').glob('transport-*.jsonl'):
   aid=int(f.stem.split('-')[-1]);ms[aid]={c['call_index']:c for c in map(json.loads,f.read_text().splitlines()) if c.get('accepted')}
  for i,e in enumerate(ev):
   if e['type']!='decide_end':continue
   v=e['data'];aid=v['agent_id'];a=actions[aid].get(v.get('raw_api_response',{}).get('id'))
   if not a:continue
   m=ms[aid][a['call_index']];belief=m['response']['choices'][0]['message']['content'];thinking=v.get('thinking');acts=v.get('tool_calls',[]);reject=[]
   for following in ev[i+1:]:
    w=following['data']
    if following['type']=='resolution':break
    if following['type']=='batch_rejected' and w.get('agent_id')==aid:reject.append(w['conflict_description'])
   records.append(dict(id=f'{model}/{p.name}/R{v["round"]}/A{aid}/C{a["call_index"]}',model=model,case=p.name,round=v['round'],agent=aid,call=a['call_index'],MS=belief,ACTION=thinking,actions=acts,rejections=reject,observation=m['request']['messages'][-2]['content'],history=m['request']['messages'][:-1],file=str((p/f'transport-agent-{aid}.jsonl').relative_to(R)),msfile=str((p/'ms'/f'transport-agent-{aid}.jsonl').relative_to(R))))

root=R;v=Path(__file__).resolve().parent
subset=[r for r in records if r['round']==0 and r['observation'].startswith('=== DECISION PHASE ===') and r['rejections'] and r['rejections'][0].startswith('Schedule targets slot') and 'occupied' in r['rejections'][0]]
assert len(subset)==5
ids=['Q/blocked_varied_s3/R0/A0/C4','Q/dense_uniform_s1/R0/A0/C4','Q/dense_varied_s1/R0/A2/C4','Q/blocked_uniform_s2/R1/A2/C9']
selected=subset+[next(r for r in records if r['id']==i) for i in ids]
notes={
'Q/dense_varied_s1/R0/A0/C4':'MS explicitly claims own occupied slot5 is free; ACTION repeats and schedules without freeing it.',
'O/blocked_varied_s3/R0/A2/C4':'MS calls own blocked slot7 free; ACTION repeats and asserts calendar shows FREE.',
'O/dense_uniform_s1/R0/A0/C4':'MS explicitly claims own occupied slot5 has no commitment; ACTION repeats; initial batch rejected.',
'O/dense_varied_s1/R0/A0/C4':'MS incorrectly judges slot5 requires no rescheduling for anyone; ACTION adds explicit false claim that own slot5 is free.',
'O/loose_varied_s1/R0/A1/C4':'MS explicitly claims own occupied slot2 is free; ACTION repeats and initial batch rejected.',
'Q/blocked_varied_s3/R0/A0/C4':'MS retains source ownership as Agent1 errand at4, but incorrectly infers willingness/need to move; ACTION newly turns that into its own reschedule from own FREE slot4 using item3, and also schedules into same target7.',
'Q/dense_uniform_s1/R0/A0/C4':'MS falsely says own slot5 free; ACTION corrects own occupancy using calendar, reschedules actual item5 to free slot2, then schedules5; no initial batch rejection.',
'Q/dense_varied_s1/R0/A2/C4':'MS recognizes Agent1 has not replied but assumes availability; ACTION drops uncertainty and says agreed upon; not a fully correct MS-to-incorrect ACTION example.',
'Q/blocked_uniform_s2/R1/A2/C9':'MS recognizes missing Agent3 confirmation, then already adds wait-for-explicit-consensus policy; ACTION carries this policy into empty action despite mandatory placement.'}
inputs={}
for r in selected:
 r['human_annotation']=notes[r['id']]
 for key in ['file','msfile']:
  p=root/r[key];inputs[r[key]]=hashlib.sha256(p.read_bytes()).hexdigest()
  calls=list(map(json.loads,p.read_text().splitlines()));c=next(x for x in calls if x['call_index']==r['call'] and x.get('accepted'))
  r['actual_'+('ms' if key=='msfile' else 'action')+'_request']=c['request']
  if key=='file':
   ep=p.parent/'events.jsonl';inputs[str(ep.relative_to(root))]=hashlib.sha256(ep.read_bytes()).hexdigest()
# For all selected nodes the ACTION retains the whole MS input unchanged, then actual MS.
for r in selected:
 a,m=r['actual_action_request']['messages'],r['actual_ms_request']['messages']
 assert a[:-2]==m and a[-2]['content']==r['MS']
(v/'MS_ERROR_ORIGIN_CASES.json').write_text(json.dumps(dict(scope='All initial DECISION occupied-target rejections for meeting round0 across both v13 belief-MS runs, plus four explicitly selected mechanism examples. Human annotations are limited to stated claims, not a full corpus semantic error rate.',exhaustive_subset_ids=[r['id'] for r in subset],examples=selected,input_sha256=inputs),ensure_ascii=False,indent=2)+'\n')
