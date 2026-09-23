import json,tarfile,statistics,itertools
from pathlib import Path
from collections import defaultdict,Counter
ROOT=Path(__file__).resolve().parents[2]
def read(path,name):
 if (ROOT/path).is_dir():return json.loads((ROOT/path/name).read_text())
 with tarfile.open(ROOT/path) as t:return json.load(t.extractfile('./'+name))
paths={'Q0':'new/q0_diagnostic_v6_evidence_20260924/q0-base-v6s-874333.tar.gz','BP99':'new/old_bp99_evidence_20260924/diagnostic/v6s-874313.tar.gz','D53':'new/d_evidence_20260924/diagnostic/d53-876226.tar.gz','D72':'new/d_evidence_20260924/diagnostic/d72-876227.tar.gz','D148':'new/d_evidence_20260924/diagnostic/d148-876228.tar.gz'}
paths['NewBP99']='runs/diagnostic/new-bp99-v6s-biinv-v1-870333'
data={n:{r['case_id']:r for r in read(p,'structure_v6/results.json') if r['replica']==0} for n,p in paths.items()}
report={};protocols={n:read(p,'structure_v6/protocol.json') for n,p in paths.items()}
report['protocol_fields']={n:{k:p.get(k) for k in ['manifest_sha256','runtime_sha256','temperature','repeats','max_tokens','seed','top_p','top_k']} for n,p in protocols.items()}
report['BP_repeat_equal']=read(paths['BP99'],'structure_v6/results.json')==read('new/old_bp99_evidence_20260924/diagnostic/v6s-870332.tar.gz','structure_v6/results.json')
conditions=['correct_B_model_P','model_B_model_P','end_to_end_P']
report['diag']={}
for n,d in data.items():
 result={'B_exact':sum(r['B']['exact'] for r in d.values()),'B_full_set':sum(len(r['model_judgment']['possible_preferences'])==3 for r in d.values())}
 for cond in conditions:
  groups=defaultdict(list)
  for r in d.values():groups[r['structure_id']].append(r)
  result[cond]={'valid':sum(r[cond]['status']=='ok' for r in d.values()),'exact_including_invalid_as_failure':sum(r[cond]['status']=='ok' and r[cond]['regret']==0 for r in d.values()),'within_01_including_invalid_as_failure':sum(r[cond]['status']=='ok' and r[cond]['regret']<=0.100000001 for r in d.values()),'both_cases_exact':sum(len(rs)==2 and all(r[cond]['status']=='ok' and r[cond]['regret']==0 for r in rs) for rs in groups.values())}
 report['diag'][n]=result
report['pairwise']={}
for a,b in itertools.combinations(data,2):
 out={}
 for cond in conditions:
  keys=[k for k in data[a] if data[a][k][cond]['status']=='ok' and data[b][k][cond]['status']=='ok'];gr=defaultdict(list)
  for k in keys:gr[data[a][k]['structure_id']].append(k)
  out[cond]={'cases':len(keys),'structures':len(gr),'regret':{n:statistics.mean(statistics.mean(data[n][k][cond]['regret'] for k in ks) for ks in gr.values()) for n in [a,b]},'b_lower_equal_higher':dict(Counter('lower' if data[b][k][cond]['regret']<data[a][k][cond]['regret'] else 'higher' if data[b][k][cond]['regret']>data[a][k][cond]['regret'] else 'equal' for k in keys))}
 report['pairwise'][a+'-'+b]=out
calpaths={'BP99':'new/old_bp99_evidence_20260924/calbench/stream24-frozen-868934.tar.gz',**{n:'new/d_evidence_20260924/calbench/'+f for n,f in [('D53','d53-874013.tar.gz'),('D19','d19-874430.tar.gz'),('D39','d39-874492.tar.gz'),('D72','d72-875168.tar.gz'),('D119','d119-875538.tar.gz'),('D148','d148-876196.tar.gz')]}}
cal={};report['calbench']={};manifests={}
for n,p in calpaths.items():
 with tarfile.open(ROOT/p) as t:
  games={}
  for m in t.getmembers():
   if m.name.startswith('./games/') and m.name.endswith('/result.json'):
    r=json.load(t.extractfile(m));games[r['game_id']]=r
  manifests[n]=json.load(t.extractfile('./games/frozen_manifest.json'))
 cal[n]=games;fam={}
 for family in ['blocked','dense','loose','replan']:
  gs=[g for k,g in games.items() if k.startswith(family)];fam[family]={'success':sum(g['metrics']['meetings_scheduled']==3 for g in gs),'meetings':sum(g['metrics']['meetings_scheduled'] for g in gs),'headline':statistics.mean(g['metrics']['headline_score'] for g in gs)}
 report['calbench'][n]={'success':sum(g['metrics']['meetings_scheduled']==3 for g in games.values()),'meetings':sum(g['metrics']['meetings_scheduled'] for g in games.values()),'headline':statistics.mean(g['metrics']['headline_score'] for g in games.values()),'strict_failures':sum(g['strict_envelope_failures'] for g in games.values()),'families':fam}
 if n!='BP99':
  report['calbench'][n]['vs_BP99']={'lost':[k for k,g in games.items() if cal['BP99'][k]['metrics']['meetings_scheduled']==3 and g['metrics']['meetings_scheduled']<3],'gained':[k for k,g in games.items() if cal['BP99'][k]['metrics']['meetings_scheduled']<3 and g['metrics']['meetings_scheduled']==3]}
report['calbench_manifest_equal']={n: m==manifests['BP99'] for n,m in manifests.items()}
(ROOT/'new/bp99_comparison_20260924/results.json').write_text(json.dumps(report,indent=2)+'\n')
print('repeat',report['BP_repeat_equal'],'manifests',report['calbench_manifest_equal'])
print('diag',json.dumps(report['diag']))
for k in ['Q0-BP99','BP99-D53','BP99-D72','BP99-D148']:print(k,json.dumps(report['pairwise'][k]))
print('cal',json.dumps(report['calbench']))
