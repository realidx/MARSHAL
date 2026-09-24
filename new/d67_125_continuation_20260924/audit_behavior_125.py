import tarfile,json,collections,pathlib
base=pathlib.Path('new/d67_125_continuation_20260924');tasks=collections.defaultdict(lambda:collections.defaultdict(list))
for arc in ['new/d67_training_20260924/d67-first-67-updates.tar.gz',str(base/'d67-125-continuation.tar.gz')]:
 with tarfile.open(arc) as t:
  for m in t:
   if '/calls/step-' not in m.name or not m.isfile():continue
   for l in t.extractfile(m):
    r=json.loads(l);tc=r['completion']['raw_message'].get('tool_calls',[]);action=tc[0]['function']['name'] if tc else 'NO_TOOL';tasks[r['task_id']][r['token_block']].append({'action':action,'reward':r['score']['reward'],'adv':r['task_advantage'],'tokens':len(r['response_ids']),'bad':r['protocol_failure'] is not None,'relevant':r['belief_action_relevant'],'kind':r['kind']})
report={}
for kind in ['O','B','Pplus']:
 ts=[sorted(es.items()) for es in tasks.values() if next(iter(es.values()))[0]['kind']==kind]; report[kind]={}
 for n in [2,3]:
  subset=[es for es in ts if len(es)>=n];out=[]
  for i in range(n):
   rs=[r for es in subset for r in es[i][1]];acts={}
   for action in sorted(set(r['action'] for r in rs)):
    xs=[r for r in rs if r['action']==action];acts[action]={'n':len(xs),'reward':sum(r['reward'] for r in xs)/len(xs),'positive_adv':sum(r['adv']>0 for r in xs),'negative_adv':sum(r['adv']<0 for r in xs)}
   out.append({'n':len(rs),'mean_tokens':sum(r['tokens'] for r in rs)/len(rs),'actions':acts,'relevant':{str(flag):{'n':len(xs:=[r for r in rs if r['relevant']==flag]),'reward':sum(r['reward'] for r in xs)/len(xs) if xs else None} for flag in [True,False]}})
  report[kind][str(n)]=out
cb={}
for p in (base/'calbench').glob('*/results.json'):
 rs=json.loads(p.read_text());name=p.parent.name.split('-')[0];cb[name]={'calls':sum(r['calls'] for r in rs),'dm':sum(r['metrics']['total_dms_sent'] for r in rs),'chars':sum(r['metrics']['total_dm_chars'] for r in rs),'events':dict(sum((collections.Counter(r['event_counts']) for r in rs),collections.Counter())),'reasons':dict(sum((collections.Counter(r['diagnostics']['invalid_action_reasons']['semantic']) for r in rs),collections.Counter())),'mismatch':sum(r['diagnostics']['coordination_failures']['new_meeting_slot_mismatches'] for r in rs),'prior_inconsistent':sum(r['diagnostics']['coordination_failures']['prior_meeting_inconsistency_rounds'] for r in rs)}
report['calbench']=cb
(base/'behavior_audit.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
