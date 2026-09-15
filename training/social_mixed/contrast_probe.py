"""Paired presentation diagnostic: three train-only tasks, two renderings, eight repeats."""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import hashlib
import json
from pathlib import Path
import threading
import time
from training.social_mixed.core import seed_for
from training.social_mixed.evaluate import complete
from training.b_sft.social_bp_training import reward
ROOT=Path(__file__).resolve().parents[2]
PACK=ROOT/'examples/social_bp/b_contrast_entry_v2'
REQUEST_FILES=('original_requests.jsonl','requests.jsonl')
EXPECTED_TASKS=3
EXPECTED_REQUESTS=6
def load():
 audit=json.loads((PACK/'audit.json').read_text())
 for name,digest in audit['files'].items():assert hashlib.sha256((PACK/name).read_bytes()).hexdigest()==digest
 tasks={t['id']:t for t in map(json.loads,(PACK/'tasks.jsonl').read_text().splitlines())}
 requests=[json.loads(x) for name in REQUEST_FILES for x in (PACK/name).read_text().splitlines()]
 assert len(tasks)==EXPECTED_TASKS and len(requests)==EXPECTED_REQUESTS
 assert all(t['split']=='train' for t in tasks.values())
 return tasks,requests,audit

def main():
 cli=argparse.ArgumentParser(description=__doc__)
 cli.add_argument('--check',action='store_true');cli.add_argument('--learner-url');cli.add_argument('--opponent-url');cli.add_argument('--output',type=Path)
 a=cli.parse_args();tasks,requests,audit=load()
 if a.check:
  from training.b_sft.build_b_response_bridges import verify_task
  for task in tasks.values():verify_task(task)
  print(f'CHECK PASSED: {len(tasks)} train tasks independently verified, {len(requests)} requests; no model calls.');return
 if not a.output or not a.learner_url or not a.opponent_url:cli.error('URLs and output required')
 a.output.mkdir(parents=True,exist_ok=False)
 (a.output/'manifest.json').write_text(json.dumps(dict(audit=audit,conditions=len(requests),repeats=8,total=len(requests)*8,temperature=1,max_tokens=1024,paired_seeds=len(REQUEST_FILES)>1,training=False),indent=2))
 locks=[threading.BoundedSemaphore(16),threading.BoundedSemaphore(16)]
 def run(job):
  reqrow,rep=job;req=dict(reqrow['request']);req['seed']=seed_for(20260916,'contrast',reqrow['task_id'],rep)
  # Both conditions use both GPUs and identical replica-to-GPU assignment.
  index=rep%2;start=time.time()
  with locks[index]:reply=complete([a.learner_url,a.opponent_url][index],['social-learner','social-base'][index],req)
  return dict(task=tasks[reqrow['task_id']],condition=reqrow['condition'],replica=rep,endpoint_index=index,elapsed_seconds=time.time()-start,response=reply,score=reward(tasks[reqrow['task_id']],reply['completion']))
 rows=[]
 try:
  with ThreadPoolExecutor(max_workers=32) as pool,(a.output/'samples.jsonl').open('w') as f:
   futures=[pool.submit(run,(req,i)) for i in range(8) for req in requests]
   for future in as_completed(futures):
    row=future.result();rows.append(row);f.write(json.dumps(row)+'\n');f.flush();print(f'contrast {len(rows)}/{len(requests)*8}',flush=True)
  summary={}
  for condition in sorted({r['condition'] for r in requests}):
   summary[condition]={}
   for tid,t in tasks.items():
    rr=[r for r in rows if r['condition']==condition and r['task']['id']==tid]
    summary[condition][t['diagnostic_group']]=dict(count=len(rr),correct=sum(r['score']['reward'] for r in rr),truncated=sum(r['response']['completion']['finish_reason']=='length' for r in rr))
  (a.output/'COMPLETE.json').write_text(json.dumps(summary,indent=2))
 except BaseException as e:
  (a.output/'INCOMPLETE.json').write_text(json.dumps(dict(error=repr(e),collected=len(rows))));raise
if __name__=='__main__':main()
