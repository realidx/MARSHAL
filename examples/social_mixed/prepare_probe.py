"""Freeze B shortcut diagnostics and P coverage without changing training data."""
import json
import hashlib
from pathlib import Path
from examples.social_mixed.audit_data import select
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'examples/social_mixed/probe_v1'
def main():
 OUT.mkdir(exist_ok=True);selected=[]
 for split in ('train','validation'):
  rows=[json.loads(x) for x in (ROOT/f'examples/social_mixed/data/bp_{split}.jsonl').read_text().splitlines()]
  b=[t for t in rows if t['task']=='B'];used=[]
  # Diagnostic categories, not certified difficulty levels. Reserve scarce controls first.
  specs=[('maintain_pair',3 if split=='train' else 1,lambda t:t['pool']=='maintain' and len(t['teacher']['gold']['possible_preferences'])==2 and t['teacher']['gold']['favored']=='undetermined'),
   ('fullset_control',3 if split=='train' else 1,lambda t:len(t['teacher']['gold']['possible_preferences'])==3 and t['teacher']['gold']['favored']=='undetermined'),
   ('complex_tendency',2,lambda t:len(t['teacher']['gold']['possible_preferences'])>1 and t['teacher']['gold']['favored']!='undetermined'),
   ('simple_exclusion',4 if split=='train' else 2,lambda t:t['pool']=='formation' and len(t['teacher']['gold']['possible_preferences'])==1),
   ('evidence_update',4 if split=='train' else 2,lambda t:t['pool']=='update')]
  for label,n,predicate in specs:
   pool=[t for t in b if t not in used and predicate(t)]
   required=[t for t in pool if t['training_source']=='l0'][:n]
   chosen=select(pool,n,required=required);used+=chosen
   selected.extend(dict(t,diagnostic_group=label) for t in chosen)
  prior=[json.loads(x) for x in (ROOT/'examples/social_mixed/audit_v1/bp_selected.jsonl').read_text().splitlines()]
  selected.extend(dict(t,diagnostic_group='P_'+t['pool']) for t in prior if t['task']=='P' and t['split']==split)
 assert len(selected)==36 and sum(t['task']=='B' for t in selected)==24
 payload=''.join(json.dumps(t,ensure_ascii=False)+'\n' for t in selected)
 (OUT/'bp.jsonl').write_text(payload)
 (OUT/'selfplay.jsonl').write_bytes((ROOT/'examples/social_mixed/audit_v1/selfplay_selected.jsonl').read_bytes())
 manifest={'version':'social-diagnostic-v1','model':'Qwen3-4B-Instruct-2507','B':24,'P':12,'bp_repeats':8,'bp_calls':288,'selfplay_resets':12,'game_repeats':4,'games':48,'temperature':1,'max_tokens':1024,'test_used':False,'selection_note':'Coverage diagnostic, not paired causal test or representative accuracy estimate; validation simple exclusion has only want examples. Files contain internal labels/worlds; only renderer output goes to model.', 'files':{n:hashlib.sha256((OUT/n).read_bytes()).hexdigest() for n in ['bp.jsonl','selfplay.jsonl']}}
 (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');print(json.dumps(manifest,indent=2))
if __name__=='__main__':main()
