"""Frozen base-model diagnostic; HTTP records are never optimizer inputs."""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import hashlib
import json
from pathlib import Path
import threading
import time
from training.social_mixed.core import Episode,seed_for
from training.social_mixed.evaluate import complete
ROOT=Path(__file__).resolve().parents[2]
PACK=ROOT/'examples/social_mixed/probe_v1'
def load():
 m=json.loads((PACK/'manifest.json').read_text());out=[]
 for name in ('bp.jsonl','selfplay.jsonl'):
  data=(PACK/name).read_bytes();assert hashlib.sha256(data).hexdigest()==m['files'][name]
  out.append([json.loads(x) for x in data.splitlines()])
 return m,*out

def main():
 cli=argparse.ArgumentParser(description=__doc__)
 cli.add_argument('--learner-url');cli.add_argument('--opponent-url')
 cli.add_argument('--output',type=Path);cli.add_argument('--check',action='store_true')
 args=cli.parse_args();manifest,bp,resets=load()
 from training.b_sft.social_named_probe import request
 from training.b_sft.social_bp_training import reward
 if args.check:
  from training.social_mixed.test_core import legal_response
  import random
  for task in bp:
   req=request(task,'action_tools',task.get('name_variant',0));assert req['messages'] and req['tools']
  for reset in resets:
   ep=Episode(reset,reset['id'],0,20260915);rng=random.Random(42)
   while ep.status=='running':ep.accept(legal_response(ep,rng))
   assert ep.status=='terminal'
  print('CHECK PASSED: 36 B/P renderings, 12 scripted terminal replays; no server/model calls.');return
 if not args.output or not args.learner_url or not args.opponent_url:cli.error('URLs and output required')
 args.output.mkdir(parents=True,exist_ok=False)
 (args.output/'manifest.json').write_text(json.dumps(manifest,indent=2))
 locks=[threading.BoundedSemaphore(16),threading.BoundedSemaphore(16)]
 urls=[args.learner_url,args.opponent_url];names=['social-learner','social-base']
 def call(req,index):
  with locks[index]:
   start=time.time();reply=complete(urls[index],names[index],req)
   reply.update(elapsed_seconds=time.time()-start,endpoint_index=index)
   return reply
 def bp_job(job):
  index,task,rep=job;req=request(task,'action_tools',task.get('name_variant',0));req['seed']=seed_for(20260915,'diagnostic',task['id'],rep)
  reply=call(req,index%2)
  return dict(task=task,replica=rep,response=reply,score=reward(task,reply['completion']))
 def game_job(job):
  index,reset,rep=job;ep=Episode(reset,reset['id'],rep,20260915)
  path=args.output/'game_calls'/f'{index:03d}.jsonl';path.parent.mkdir(exist_ok=True)
  with path.open('w') as f:
   while ep.status=='running':
    ep.accept(call(ep.request(),index%2));f.write(json.dumps(ep.calls[-1])+'\n');f.flush()
  return dict(ep.summary(),calls=ep.calls,reset=reset,job_index=index)
 results={}
 try:
  for stage,fn,jobs in [('bp',bp_job,[(i,t,r) for i,(t,r) in enumerate((t,r) for t in bp for r in range(8))]),('games',game_job,[(i,t,r) for i,(t,r) in enumerate((t,r) for t in resets for r in range(4))])]:
   start=time.time();records=[]
   with ThreadPoolExecutor(max_workers=32) as pool,(args.output/(stage+'.jsonl')).open('w') as f:
    futures=[pool.submit(fn,j) for j in jobs]
    for future in as_completed(futures):
     row=future.result();f.write(json.dumps(row)+'\n');f.flush();records.append(row)
     print(f'{stage}: {len(records)}/{len(jobs)} elapsed={time.time()-start:.1f}s',flush=True)
   results[stage]={'count':len(records),'seconds':time.time()-start}
   if stage=='bp':results[stage]['correct']=sum(r['score']['reward'] for r in records)
   else:results[stage]['terminal']=sum(r['status']=='terminal' for r in records)
  (args.output/'COMPLETE.json').write_text(json.dumps(results,indent=2)+'\n')
 except BaseException as e:
  (args.output/'INCOMPLETE.json').write_text(json.dumps({'error':repr(e),'finished_stages':results},indent=2));raise
if __name__=='__main__':main()
