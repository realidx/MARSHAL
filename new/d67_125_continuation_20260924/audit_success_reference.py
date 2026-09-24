import json,pathlib,tarfile,collections
R=pathlib.Path('new/d67_125_continuation_20260924'); old={};trans={};diagnoses={}
with tarfile.open('new/old_bp99_evidence_20260924/calbench/stream24-frozen-868934.tar.gz') as t:
 for m in t:
  if m.name.endswith('/results.json'):old={r['game_id']:r for r in json.load(t.extractfile(m))}
  if '/transport-agent-' in m.name and m.name.endswith('.jsonl'):trans[(m.name.split('/')[-2],m.name.split('/')[-1])]=[json.loads(l) for l in t.extractfile(m)]
models={'oldBP99':old}
for p in (R/'calbench').glob('*/results.json'):models[p.parent.name.split('-')[0]]={r['game_id']:r for r in json.loads(p.read_text())}
out={'calbench':{},'diagnostic_common':{}}
for name,rs in models.items():
 out['calbench'][name]={'success':sum(r['coordinated_success'] for r in rs.values()),'headline':sum(r['metrics']['headline_score'] for r in rs.values())/24,'meetings':sum(r['diagnostics']['final_valid_meetings'] for r in rs.values()),'old_success_lost':[k for k in old if old[k]['coordinated_success'] and not rs[k]['coordinated_success']],'new_success':[k for k in old if not old[k]['coordinated_success'] and rs[k]['coordinated_success']]}
for name in ['oldBP99','d67','d79','d99','d119']:
 print(name,out['calbench'][name])
for game in ['replan_uniform_s2','replan_uniform_s3','loose_uniform_s1']:
 print('OLD TRACE',game)
 for (g,f),rows in trans.items():
  if g!=game:continue
  dec=[]
  for r in rows:
   try:x=json.loads(r.get('normalized_text',''))
   except:continue
   for a in x.get('actions',[]):
    if a.get('type')=='schedule':dec.append((a.get('meeting_id'),a.get('slot')))
  print(f,dec)
with tarfile.open('new/old_bp99_evidence_20260924/diagnostic/v6s-874313.tar.gz') as t:
 m=next(m for m in t if m.name.endswith('/structure_v6/results.json'));diagnoses['oldBP99']=json.load(t.extractfile(m))
for p in pathlib.Path('new/d_diagnostic_v6s_20260924').glob('*/structure_v6/results.json'):diagnoses[p.parents[1].name.split('-')[0]]=json.loads(p.read_text())
with tarfile.open('new/q0_diagnostic_v6_evidence_20260924/q0-base-v6s-874333.tar.gz') as t:
 m=next(m for m in t if m.name.endswith('/structure_v6/results.json'));diagnoses['Q0']=json.load(t.extractfile(m))
idx={n:{(r['case_id'],r['replica']):r for r in rs} for n,rs in diagnoses.items()}
for cond in ['correct_B_model_P','end_to_end_P']:
 keys=set.intersection(*(set(d) for d in idx.values()));keys={k for k in keys if all(d[k][cond]['status']=='ok' for d in idx.values())}
 vals={}
 for n,d in idx.items():
  group=collections.defaultdict(list)
  for k in keys:group[d[k]['structure_id']].append(d[k][cond]['regret'])
  vals[n]=sum(sum(v)/len(v) for v in group.values())/len(group)
 out['diagnostic_common'][cond]={'rows':len(keys),'structures':len(group),'regret':vals}
print('DIAG COMMON',out['diagnostic_common']);(R/'success_reference_comparison.json').write_text(json.dumps(out,indent=2))
