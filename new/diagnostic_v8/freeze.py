"""Freeze layered cases after native qualification; never reads model outcomes."""
import json,hashlib
from collections import Counter
from pathlib import Path
from new.diagnostic_v8.experiment import p_request
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 pool=json.loads((HERE/'qualified_pool.json').read_text());selected=[];used=set();counts=Counter()
 # Direct feedback is a small grounding check, not replicated to pretend diversity.
 targets={'direct_feedback':3,'single_elimination':8,'single_ambiguous':8,'multi_update':8}
 for layer,n in targets.items():
  candidates=[c for c in pool if c['difficulty_layer']==layer]
  for _ in range(n):
   remaining=[c for c in candidates if c['id'] not in used]
   if not remaining:raise RuntimeError('Insufficient '+layer)
   c=min(remaining,key=lambda c:(sum(s['source_parent']==c['source_parent'] for s in selected),sum(s['structure_family']==c['structure_family'] for s in selected),counts[layer,c['intervention_qualification']['role']],c['structural_difficulty']['goals'],c['id']))
   selected.append(c);used.add(c['id']);counts[layer,c['intervention_qualification']['role']]+=1
 for j,c in enumerate(selected):
  c['case_number']=j+1;c['requests']['P_clean']=p_request(c,c['gold_judgment'])
 (HERE/'cases.json').write_text(json.dumps(selected,indent=2)+'\n')
 files=['cases.json','generation_audit.json'];deps=['new/diagnostic_v8/'+f for f in ['build.py','freeze.py','experiment.py']]
 deps+=list(json.loads((ROOT/'new/diagnostic_v7p/manifest.json').read_text())['dependencies'])
 manifest=dict(version='v8-evidence-layered',cases=len(selected),conditions=['B','O','P_gold','P_model'],calls_per_repeat_max=4*len(selected),difficulty_counts=dict(Counter(c['difficulty_layer'] for c in selected)),role_counts=dict(Counter(c['intervention_qualification']['role'] for c in selected)),selection='Teacher-qualified structure and evidence only; no model results read',files={f:sha(HERE/f) for f in files},dependencies={p:sha(ROOT/p) for p in deps})
 (HERE/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');print(json.dumps({k:v for k,v in manifest.items() if k not in ['files','dependencies']},indent=2))
if __name__=='__main__':main()
