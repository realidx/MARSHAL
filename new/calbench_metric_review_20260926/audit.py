import tarfile,json,statistics as st
from collections import defaultdict
from pathlib import Path
paths=[('Q0','new/q0_calbench_24_repeats_20260924/runs/frozen-5of24-868929.tar.gz'),('oldBP99','new/old_bp99_evidence_20260924/calbench/stream24-frozen-868934.tar.gz'),('micro24','new/micro_learning_evidence_20260925/calbench_micro24.tar.gz'),('micro13','new/micro_learning_evidence_20260925/calbench_micro13.tar.gz'),('D24v2','new/micro_v2_evidence_20260925/calbench_d24v2.tar.gz'),('OP16v2','new/micro_v2_evidence_20260925/calbench_op16v2.tar.gz')]
out={}
for label,path in paths:
 groups=defaultdict(list)
 with tarfile.open(path) as t:
  names=set(t.getnames())
  for n in names:
   if not n.endswith('/result.json'):continue
   d=json.load(t.extractfile(n))
   if 'metrics' not in d or 'meetings_scheduled' not in d['metrics']:continue
   key=n.split('/games/')[0] if '/games/' in n else label
   folder=n.rsplit('/',1)[0]
   sn=folder+'/scenario.json'
   scenario=json.load(t.extractfile(sn))
   if 'scenario' in scenario:scenario=scenario['scenario']
   m=d['metrics']; ids=set(m.get('scheduled_meeting_ids',[])); num=m['num_agents']
   ratios=[sum(x['id'] in ids for x in scenario['meetings'] if a in x['participants'])/sum(a in x['participants'] for x in scenario['meetings']) for a in range(num)]
   groups[key].append(dict(id=d.get('game_id',folder),meetings=m['meetings_scheduled'],success=d.get('coordinated_success',d.get('diagnostics',{}).get('full_stream_completion')),optimal=d.get('successful_and_optimal'),coord=st.mean(ratios),cost=st.mean(m['per_agent_coordination_cost']) if 'per_agent_coordination_cost' in m else None,fair=st.mean(m['per_agent_fairness_cost']) if 'per_agent_fairness_cost' in m else None,comm=st.mean(m['per_agent_communication_efficiency']) if 'per_agent_communication_efficiency' in m else None,headline=m['headline_score'],realized=m['realized_cost']))
 for key,rows in groups.items():
  res={'games':len(rows),'meetings':sum(x['meetings'] for x in rows),'success':sum(bool(x['success']) for x in rows),'optimal':sum(bool(x['optimal']) for x in rows)}
  for field in ['coord','cost','fair','comm','headline','realized']:
   vals=[x[field] for x in rows if x[field] is not None];res[field]=st.mean(vals) if len(vals)==len(rows) else None
  out[label+':'+key]={'summary':res,'rows':rows};print(label,key,json.dumps(res))
Path('/tmp/calbench_metrics_audit/results.json').write_text(json.dumps(out,indent=2))
