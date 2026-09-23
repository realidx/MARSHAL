import tarfile,json,statistics
from pathlib import Path
from collections import defaultdict,Counter
ROOT=Path(__file__).resolve().parents[2]
paths={'Q0':'new/q0_diagnostic_v6_evidence_20260924/q0-base-v6s-874333.tar.gz','D53':'new/d_evidence_20260924/diagnostic/d53-876226.tar.gz','D72':'new/d_evidence_20260924/diagnostic/d72-876227.tar.gz','D148':'new/d_evidence_20260924/diagnostic/d148-876228.tar.gz'}
data={};report={}
for name,p in paths.items():
 with tarfile.open(ROOT/p) as t:
  rows=json.load(t.extractfile('./structure_v6/results.json'))
 data[name]={(r['case_id'],r['replica']):r for r in rows}
 groups=defaultdict(list)
 for r in rows:groups[r['case_id']].append(r)
 report[name]={'B_exact':sum(r['B']['exact'] for r in rows)/len(rows),'repeat_disagreements':{condition:sum(len({json.dumps(r[condition],sort_keys=True) for r in rs})>1 for rs in groups.values()) for condition in ['B','correct_B_model_P','model_B_model_P','end_to_end_P']},'B_judgments':dict(Counter(json.dumps(r['model_judgment'],sort_keys=True) for r in rows))}
common={}
for condition in ['correct_B_model_P','model_B_model_P','end_to_end_P']:
 keys=set.intersection(*(set(d) for d in data.values()));keys={k for k in keys if all(d[k][condition]['status']=='ok' for d in data.values())}
 values={}
 for name,d in data.items():
  groups=defaultdict(list)
  for k in keys:groups[d[k]['structure_id']].append(d[k][condition]['regret'])
  values[name]=statistics.mean(statistics.mean(v) for v in groups.values())
 common[condition]=dict(rows=len(keys),cases=len({k[0] for k in keys}),structures=len(groups),structure_weighted_regret=values)
keys={k for k in data['Q0'] if all(d[k][c]['status']=='ok' for d in data.values() for c in ['correct_B_model_P','model_B_model_P'])}
gains={}
for name,d in data.items():
 g=defaultdict(list)
 for k in keys:g[d[k]['structure_id']].append(d[k]['model_B_model_P']['regret']-d[k]['correct_B_model_P']['regret'])
 gains[name]=statistics.mean(statistics.mean(v) for v in g.values())
common['repair']=dict(rows=len(keys),structures=len(g),gain=gains)
report['common_valid']=common
(ROOT/'new/d_review_20260924/diagnostic_audit.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
