"""Compare frozen Q0 repeats and frozen trained checkpoints, no model calls."""
import json,tarfile,statistics
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
paths={'Q0a':'new/q0_calbench_24_repeats_20260924/runs/frozen-5of24-868929.tar.gz','Q0b':'new/q0_calbench_24_repeats_20260924/runs/frozen-5of24-868930.tar.gz','BP99':'new/old_bp99_evidence_20260924/calbench/stream24-frozen-868934.tar.gz',**{n:'new/d_evidence_20260924/calbench/'+f for n,f in [('D19','d19-874430.tar.gz'),('D39','d39-874492.tar.gz'),('D53','d53-874013.tar.gz'),('D72','d72-875168.tar.gz'),('D119','d119-875538.tar.gz'),('D148','d148-876196.tar.gz')]}}
data={};meta={};out={}
for name,p in paths.items():
 with tarfile.open(ROOT/p) as t:
  data[name]={}
  for m in t.getmembers():
   if m.name.startswith('./games/') and m.name.endswith('/result.json'):
    r=json.load(t.extractfile(m));data[name][r['game_id']]=r
  meta[name]={k:json.load(t.extractfile('./'+file)) for k,file in [('manifest','games/frozen_manifest.json'),('protocol','games/execution_protocol.json'),('runtime','runtime_environment.json')]}
for name,gs in data.items():
 q=data['Q0a'];success=lambda g:g['metrics']['meetings_scheduled']==3
 summary={'success':sum(success(g) for g in gs.values()),'meetings':sum(g['metrics']['meetings_scheduled'] for g in gs.values()),'headline':statistics.mean(g['metrics']['headline_score'] for g in gs.values()),'format_failures':sum(g['strict_envelope_failures'] for g in gs.values()),'gained':[k for k in gs if success(gs[k]) and not success(q[k])],'lost':[k for k in gs if success(q[k]) and not success(gs[k])],'families':{}}
 for fam in ['blocked','dense','loose','replan']:
  subset=[g for k,g in gs.items() if k.startswith(fam)];summary['families'][fam]=[sum(success(g) for g in subset),sum(g['metrics']['meetings_scheduled'] for g in subset)]
 summary['manifest_matches_Q0']=meta[name]['manifest']==meta['Q0a']['manifest'];summary['protocol_matches_Q0']=meta[name]['protocol']==meta['Q0a']['protocol']
 out[name]=summary
out['repeat_headline_equal']=all(data['Q0a'][k]['metrics']['headline_score']==data['Q0b'][k]['metrics']['headline_score'] for k in data['Q0a'])
(ROOT/'new/bp99_comparison_20260924/q0_calbench.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps(out,indent=2))
