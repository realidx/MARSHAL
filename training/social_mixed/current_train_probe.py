"""Frozen proportional train-only BP sample, then random full-game self-play."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from training.social_mixed import probe, selfplay_probe
ROOT=Path(__file__).resolve().parents[2]
PACK=ROOT/'examples/social_mixed/current_train_probe_v2'

def load_bp():
 m=json.loads((PACK/'manifest.json').read_text());data=(PACK/'bp.jsonl').read_bytes()
 assert hashlib.sha256(data).hexdigest()==m['bp_sha256']
 rows=[json.loads(x) for x in data.splitlines()]
 from training.b_sft.social_named_probe import request
 frozen=(PACK/'requests.jsonl').read_bytes()
 assert hashlib.sha256(frozen).hexdigest()==m['requests_sha256']
 expected={r['task_id']:r['request'] for r in map(json.loads,frozen.splitlines())}
 for name,checksum in m['source_sha256'].items():
  assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==checksum, f'Prompt source changed: {name}; re-review and rebuild before model calls'
 for t in rows:
  assert request(t,'action_tools',t.get('name_variant',0))==expected[t['id']], f'Actual request differs from reviewed request: {t["id"]}' 
 assert all(t['split']=='train' for t in rows)
 return m,rows,[]

def main():
 p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');p.add_argument('--learner-url');p.add_argument('--opponent-url');p.add_argument('--output',type=Path);p.add_argument('--stage',choices=['bp','sp'])
 a=p.parse_args()
 if a.stage=='bp':
  probe.load=load_bp
  sys.argv=[sys.argv[0],'--learner-url',a.learner_url,'--opponent-url',a.opponent_url,'--output',str(a.output)]
  probe.main()
  records=[json.loads(x) for x in (a.output/'bp.jsonl').read_text().splitlines()]
  from training.b_sft.social_bp_training import summarize
  split={name:[r for r in records if bool(r['task'].get('probe_diagnostic_only'))==flag] for name,flag in [('training_core',False),('diagnostic_only',True)]}
  (a.output/'stratified_summary.json').write_text(json.dumps({name:summarize(rs) for name,rs in split.items()},indent=2)+'\n')
  return
 if a.stage=='sp':
  original=selfplay_probe.load
  def train_load():
   m,rows=original();return m,[r for r in rows if r['split']=='train']
  selfplay_probe.load=train_load
  sys.argv=[sys.argv[0],'--learner-url',a.learner_url,'--opponent-url',a.opponent_url,'--output',str(a.output)]
  selfplay_probe.main()
  return
 m,bp,_=load_bp()
 if a.check:
  from training.b_sft.social_named_probe import request
  for t in bp:
   req=request(t,'action_tools',t.get('name_variant',0));assert req['messages'] and req['tools']
  print(json.dumps(dict(bp_tasks=len(bp),bp_samples=len(bp)*8,selfplay_check=selfplay_probe.check(),model_calls=0)),flush=True);return
 if not (a.output and a.learner_url and a.opponent_url):p.error('URLs and output required')
 a.output.mkdir(parents=True,exist_ok=False)
 errors=[]
 for stage in ('bp','sp'):
  status=subprocess.run([sys.executable,'-u','-m',__spec__.name,'--stage',stage,'--learner-url',a.learner_url,'--opponent-url',a.opponent_url,'--output',str(a.output/stage)]).returncode
  if status:errors.append(dict(stage=stage,exit_code=status))
 (a.output/('INCOMPLETE.json' if errors else 'COMPLETE.json')).write_text(json.dumps(dict(errors=errors,bp_manifest=m),indent=2)+'\n')
 if errors:raise RuntimeError(str(errors))
if __name__=='__main__':main()
