"""Three independent players, one checkpoint, one deterministic rollout per reset."""
import argparse,json,hashlib,time
from pathlib import Path
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from urllib.request import Request,urlopen
from examples.final_evaluation.adversarial_runtime import play
from training.social_mixed.structure_coverage import geometry_id
ROOT=Path(__file__).resolve().parents[2]
FREEZE=Path(__file__).with_name('team_benac_v1')
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def audit():
 source=Path(__file__).with_name('adversarial_v2')
 old=json.loads((source/'manifest.json').read_text())
 for name,h in old['files'].items():
  if digest(source/name)!=h:raise ValueError('Original suite file changed: '+name)
 rows=[json.loads(l) for l in (source/'resets.jsonl').read_text().splitlines()]
 files=sorted({p for p in (ROOT/'examples/social_mixed').rglob('*.jsonl') if p.name in ('bp_train.jsonl','bp_validation.jsonl','selfplay_train.jsonl','selfplay_validation.jsonl','tasks.jsonl','augmented_tasks.jsonl')})
 matches={r['id']:[] for r in rows};hashes={};cache={}
 for p in files:
  hashes[str(p.relative_to(ROOT))]=digest(p);families=set()
  for line in p.read_text().splitlines():
   row=json.loads(line);t=row['task'] if isinstance(row.get('task'),dict) else row
   inp=t.get('input',t.get('raw',{}));g=inp.get('game')
   if not g:continue
   key=json.dumps(g,sort_keys=True)
   if key not in cache:cache[key]=geometry_id(g)
   families.add(cache[key])
  for r in rows:
   if geometry_id(r['raw']['game']) in families:matches[r['id']].append(str(p.relative_to(ROOT)))
 FREEZE.mkdir(exist_ok=True)
 for r in rows:
  r['historical_split']=r['evaluation_split']
  r['evaluation_split']='seen_in_audited_banks' if matches[r['id']] else 'unseen_in_audited_banks'
 (FREEZE/'resets.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
 report=dict(scope='Union of listed local training/validation banks; per-model ID is not implied. Includes historical banks.',source_hashes=hashes,matches=matches,split_counts=dict(Counter(r['evaluation_split'] for r in rows)))
 (FREEZE/'overlap_audit.json').write_text(json.dumps(report,indent=2)+'\n')
 manifest=dict(version='team-benac-v1',players=3,games=16,repeats=1,temperature=0,max_tokens=1024,retries=1,original_manifest_sha256=digest(source/'manifest.json'),files={n:digest(FREEZE/n) for n in ('resets.jsonl','overlap_audit.json')})
 (FREEZE/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');return report

def load():
 m=json.loads((FREEZE/'manifest.json').read_text())
 for n,h in m['files'].items():
  if digest(FREEZE/n)!=h:raise ValueError('Changed frozen file: '+n)
 return m,[json.loads(l) for l in (FREEZE/'resets.jsonl').read_text().splitlines()]

def complete(route,request):
 body=dict(request,model=route['model'],temperature=0,top_p=1,top_k=-1,max_tokens=1024,repetition_penalty=1,tool_choice='auto',parallel_tool_calls=False)
 # Episode requests contain only native chat fields and seed.
 body={k:v for k,v in body.items() if k in ('messages','tools','model','temperature','top_p','top_k','max_tokens','repetition_penalty','tool_choice','parallel_tool_calls','seed')}
 req=Request(route['base_url'].rstrip('/')+'/chat/completions',data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer EMPTY'})
 start=time.monotonic()
 with urlopen(req,timeout=600) as response:raw=json.load(response)
 c=raw['choices'][0]
 if c['finish_reason'] not in ('stop','tool_calls','length'):raise ValueError('Unknown finish reason')
 return dict(completion=dict(raw_message=c['message'],finish_reason=c['finish_reason']),usage=raw.get('usage',{}),request=body,response=raw,elapsed_seconds=time.monotonic()-start)

def team_game(reset,route,output,generate=complete):
 seats=play(reset,0,0,{'q0':route,'focal':route},output,generate,shared=True)
 r=seats[0];bounds=None if any(x['missing_utility_bounds'] is None for x in seats) else [sum(x['missing_utility_bounds'][k] for x in seats) for k in ('lower','upper')]
 return dict(case_id=r['case_id'],status=r['status'],split=r['split'],mode=r['mode'],utilities=r['utilities'],total_utility=r['total_utility'],team_bounds=bounds,calls=sum(x['focal_calls'] for x in seats),invalid_calls=sum(x['focal_invalid_calls'] for x in seats),truncated_calls=sum(x['focal_truncated_calls'] for x in seats))

def summarize(rows):
 result={}
 for split in ['all']+sorted({r['split'] for r in rows}):
  for mode in ['all','binary','linear']:
   rr=[r for r in rows if (split=='all' or r['split']==split) and (mode=='all' or r['mode']==mode)]
   if not rr:continue
   done=[r for r in rr if r['status']=='terminal']
   result[split+'/'+mode]=dict(games=len(rr),complete=len(done),conditional_team_utility=sum(r['total_utility'] for r in done)/len(done) if done else None,conditional_per_player=[sum(r['utilities'][i] for r in done)/len(done) for i in range(3)] if done else None,full_cohort_team_bounds=[sum(r['team_bounds'][i] for r in rr)/len(rr) for i in (0,1)] if all(r['team_bounds'] is not None for r in rr) else None,invalid_calls=sum(r['invalid_calls'] for r in rr),truncated_calls=sum(r['truncated_calls'] for r in rr))
 return result

def main():
 p=argparse.ArgumentParser();p.add_argument('--audit',action='store_true');p.add_argument('--base-url');p.add_argument('--model');p.add_argument('--checkpoint-hash');p.add_argument('--output',type=Path);p.add_argument('--parallel-games',type=int,default=4);p.add_argument('--batch-invariant-confirmed',action='store_true');a=p.parse_args()
 if a.audit:print(json.dumps(audit()['split_counts']));return
 if not all((a.base_url,a.model,a.checkpoint_hash,a.output,a.batch_invariant_confirmed)) or a.parallel_games<1:p.error('Require endpoint, model, checkpoint hash, output and confirmed batch-invariant service')
 m,resets=load();a.output.mkdir(parents=True,exist_ok=False);route=dict(base_url=a.base_url,model=a.model)
 (a.output/'protocol.json').write_text(json.dumps(dict(suite=m,route=route,checkpoint_hash=a.checkpoint_hash,homogeneous_team=True,batch_invariant_operator_confirmed=True,temperature=0,replicas=1,source_sha256=digest(Path(__file__))),indent=2))
 rows=[]
 with ThreadPoolExecutor(max_workers=a.parallel_games) as pool:
  for start in range(0,len(resets),a.parallel_games):
   rows.extend(pool.map(lambda r:team_game(r,route,a.output),resets[start:start+a.parallel_games]))
   (a.output/'results.json').write_text(json.dumps(rows,indent=2));(a.output/'summary.json').write_text(json.dumps(summarize(rows),indent=2))
   if any(r['status']=='infrastructure_failure' for r in rows):raise RuntimeError('Infrastructure failure; stopped, see raw calls')
 (a.output/'COMPLETE.json').write_text(json.dumps(dict(games=len(rows))))
if __name__=='__main__':main()
