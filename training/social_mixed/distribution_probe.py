"""Frozen four-background diagnostic; HTTP outputs are evaluation-only."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from collections import Counter
from training.social_mixed import probe, selfplay_probe
from training.social_mixed.core import DATA, load_data
from training.social_mixed.distribution_sampling import groups
from training.b_sft.preference_contract import PROFILES
from training.b_sft.social_named_probe import request
ROOT=Path(__file__).resolve().parents[2]
PACK=ROOT/'examples/social_mixed/distribution_probe_v1'

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path):return [json.loads(s) for s in path.read_text().splitlines()]
def prepare():
 data=load_data();bp=[]
 # Same semantic unit under all four priors, with scoring/control pairs intact.
 chosen={'B1':'partial_helpful','B2':'target_offer_control','B3':'joint_favored',
         'P1':'response_social','P2':'joint_correlation','P3':'qualitative_contrasts','P4':'acquisition_and_use'}
 units=groups(data['bp_train'])
 for kernel,case in chosen.items():
  for profile in PROFILES:bp+=units[kernel,profile,case]
 # Small validation sample; retain all profile siblings of each selected origin.
 for kernel in chosen:
  candidates=[t for t in data['bp_validation'] if t['kernel']==kernel and t['background_profile']=='balanced']
  candidates.sort(key=lambda t:hashlib.sha256(('20260916:'+t['origin_id']).encode()).hexdigest())
  origin=candidates[0]['origin_id']
  bp += [t for t in data['bp_validation'] if t['origin_id']==origin]
 # Include all result branches linked to the selected P4 parent, even zero-contrast diagnostics.
 diag=read(DATA/'diagnostics.jsonl')
 bp+=diag
 for t in bp:t['probe_diagnostic_only']=bool(t.get('diagnostic_only'))
 sp=[]
 for split in ('train','validation'):
  base=[r for r in data['selfplay_'+split] if r['background_profile']=='balanced']
  strata={}
  for r in base:
   mode=tuple(sorted({bool(g['binary']) for g in r['raw']['game']['goals']}))
   strata.setdefault((r['players'],mode),[]).append(r)
  for key,rows in sorted(strata.items()):
   r=min(rows,key=lambda r:hashlib.sha256(('20260916:'+r['id']).encode()).hexdigest())
   sp += [x for x in data['selfplay_'+split] if x['geometry_source_id']==r['geometry_source_id']]
 PACK.mkdir(exist_ok=True)
 payloads={'bp.jsonl':bp,'selfplay.jsonl':sp,'requests.jsonl':[dict(task_id=t['id'],request=request(t,'action_tools',t.get('name_variant',0))) for t in bp]}
 for name,rows in payloads.items():(PACK/name).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
 manifest=dict(version='distribution-probe-v1',dataset_manifest_sha256=digest(DATA/'manifest.json'),
  files={n:digest(PACK/n) for n in payloads},bp_tasks=len(bp),bp_samples=len(bp)*8,selfplay_resets=len(sp),selfplay_games=len(sp)*4,
  bp_strata=dict(Counter(t['split']+':'+t['kernel'] for t in bp)),diagnostics=len(diag),
  selection='Fixed semantic train contrast units with four prior siblings; one validation origin per kernel with four siblings; random-bank selfplay stratified by split/player count/scoring, no outcome selection.',
  max_tokens=1024,repeats_bp=8,repeats_sp=4,concurrency_per_gpu=16)
 (PACK/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');print(json.dumps(manifest,indent=2))

def load():
 load_data() # Verify data and live prompt dependency hashes.
 m=json.loads((PACK/'manifest.json').read_text())
 assert digest(DATA/'manifest.json')==m['dataset_manifest_sha256'],'Dataset changed; rebuild probe'
 for n,h in m['files'].items():assert digest(PACK/n)==h,n
 bp=read(PACK/'bp.jsonl');sp=read(PACK/'selfplay.jsonl')
 expected={r['task_id']:r['request'] for r in read(PACK/'requests.jsonl')}
 for t in bp:
  assert t['split'] in ('train','validation')
  assert request(t,'action_tools',t.get('name_variant',0))==expected[t['id']]
 assert all(r['split'] in ('train','validation') for r in sp)
 return m,bp,sp

def main():
 p=argparse.ArgumentParser();p.add_argument('--prepare',action='store_true');p.add_argument('--check',action='store_true')
 p.add_argument('--stage',choices=['bp','sp']);p.add_argument('--learner-url');p.add_argument('--opponent-url');p.add_argument('--output',type=Path)
 a=p.parse_args()
 if a.prepare:prepare();return
 m,bp,sp=load()
 if a.check:
  selfplay_probe.load=lambda:(m,sp)
  result=selfplay_probe.check()
  print(json.dumps(dict(bp_tasks=len(bp),bp_samples=len(bp)*8,selfplay_resets=len(sp),selfplay_games=len(sp)*4,**result)),flush=True);return
 if not(a.output and a.learner_url and a.opponent_url):p.error('URLs and output required')
 if a.stage:
  sys.argv=[sys.argv[0],'--learner-url',a.learner_url,'--opponent-url',a.opponent_url,'--output',str(a.output)]
  if a.stage=='bp':
   probe.load=lambda:(m,bp,[]);probe.main()
   from training.b_sft.social_bp_training import summarize
   rows=read(a.output/'bp.jsonl');strata={}
   for r in rows:
    t=r['task'];key=':'.join((t['split'],t['kernel'],t['background_profile'],'diagnostic' if t['probe_diagnostic_only'] else 'core'))
    strata.setdefault(key,[]).append(r)
   (a.output/'stratified_summary.json').write_text(json.dumps({k:summarize(v) for k,v in strata.items()},indent=2)+'\n')
  else:
   selfplay_probe.load=lambda:(m,sp);selfplay_probe.main()
  return
 a.output.mkdir(parents=True,exist_ok=False);errors=[]
 for stage in ('bp','sp'):
  rc=subprocess.run([sys.executable,'-u','-m','training.social_mixed.distribution_probe','--stage',stage,'--learner-url',a.learner_url,'--opponent-url',a.opponent_url,'--output',str(a.output/stage)]).returncode
  if rc:errors.append(dict(stage=stage,exit_code=rc))
 (a.output/('INCOMPLETE.json' if errors else 'COMPLETE.json')).write_text(json.dumps(dict(errors=errors,manifest=m),indent=2)+'\n')
 if errors:raise RuntimeError(str(errors))
if __name__=='__main__':main()
