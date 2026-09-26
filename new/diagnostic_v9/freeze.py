import json,hashlib
from pathlib import Path
from collections import Counter
from new.diagnostic_v9.experiment import p_request
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 pool=json.loads((HERE/'pool.json').read_text())
 for c in pool:c['measurement_level']='basic'
 advanced=[c for c in json.loads((ROOT/'new/diagnostic_v8/cases.json').read_text()) if c['difficulty_layer']=='multi_update' or (c['difficulty_layer'].startswith('single_') and c['intervention_qualification']['role']=='repair_sensitive')]
 for c in advanced:c['measurement_level']='challenge'
 pool+=advanced;selected=[]
 for layer,n in [('direct_feedback',6),('single_elimination',6),('single_ambiguous',6),('multi_update',4)]:
  for _ in range(n):
   available=[c for c in pool if c['difficulty_layer']==layer and c['id'] not in {s['id'] for s in selected}]
   if layer.startswith('single_'):
    level='basic' if _<3 else 'challenge'
    available=[c for c in available if c['measurement_level']==level]
   if not available:raise ValueError('Insufficient '+layer)
   c=min(available,key=lambda c:(sum(s['source_parent']==c['source_parent'] for s in selected),c['intervention_qualification']['role']!='repair_sensitive',sum(s['gold_judgment']==c['gold_judgment'] and s['difficulty_layer']==layer for s in selected),len(c['task']['input']['game']['goals']),c['id']))
   selected.append(c)
 for j,c in enumerate(selected):
  c['case_number']=j+1
  c['requests']['B']['messages'][1]['content']+='\npossible_preferences is the set supported by the evidence, not a list of all allowed label names. A truthful investigation answer leaves only the revealed preference possible. The submitted set and favored must express the judgment in your explanation.'
  c['requests']['P_clean']=p_request(c,c['gold_judgment'])
 if sum(c['intervention_qualification']['role']=='repair_sensitive' for c in selected)<3:raise ValueError('No sufficient action-sensitive checks')
 (HERE/'cases.json').write_text(json.dumps(selected,indent=2)+'\n')
 deps=json.loads((ROOT/'new/diagnostic_v8/manifest.json').read_text())['dependencies'];deps.update({f'new/diagnostic_v9/{f}':sha(HERE/f) for f in ['build.py','freeze.py','experiment.py']})
 manifest=dict(version='v9-small-evidence-action',cases=len(selected),calls_per_repeat_max=len(selected)*4,conditions=['B','O','P_gold','P_model'],difficulty_counts=dict(Counter(c['difficulty_layer'] for c in selected)),role_counts=dict(Counter(c['intervention_qualification']['role'] for c in selected)),files={f:sha(HERE/f) for f in ['cases.json','audit.json']},dependencies=deps)
 (HERE/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
 lines=['# Frozen case audit','', 'No model outcomes used for selection. Numbers below are auditor-only; not supplied to the model.','']
 for c in selected:
  lines += [f"## {c['case_number']}. {c['id']}",f"{c['difficulty_layer']} / {c['intervention_qualification']['role']}; goals={len(c['task']['input']['game']['goals'])}; parent={c['source_parent']}",'','Gold: '+json.dumps(c['gold_judgment']),'Evidence: '+json.dumps(c['evidence_trace']),'Reward-accepted indices: '+str(c['certificate']['acceptable_action_indices']),'World-specific reward sets: '+json.dumps(c['intervention_qualification']['world_reward_sets']),'']
 (HERE/'CASE_AUDIT.md').write_text('\n'.join(lines)+'\n');print(json.dumps({k:v for k,v in manifest.items() if k not in ['files','dependencies']},indent=2))
if __name__=='__main__':main()
