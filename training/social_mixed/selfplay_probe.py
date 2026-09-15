"""Full-game random-bank base probe. HTTP logs are evaluation-only, not training data."""
import argparse,hashlib,json,random,threading,time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import numpy as np
from training.social_mixed.core import Episode
from training.social_mixed.evaluate import complete
from training.social_mixed.prepare_selfplay_audit import OUT,SEED
from training.social_mixed import policy_prompt

def load():
 m=json.loads((OUT/'manifest.json').read_text());payload=(OUT/'probe_resets.jsonl').read_bytes()
 assert hashlib.sha256(payload).hexdigest()==m['files']['probe_resets.jsonl']['sha256']
 rows=[json.loads(s) for s in payload.splitlines()];assert all(r['split']!='test' for r in rows)
 return m,rows

def check():
 from training.social_mixed.test_core import legal_response
 m,resets=load();episodes=0
 for reset in resets:
  for replica in range(2):
   ep=Episode(reset,reset['id'],replica,SEED);rng=random.Random(SEED+replica)
   while ep.status=='running':
    req=ep.request();assert 'Briefly' in str(req) or 'brief' in str(req)
    ep.accept(legal_response(ep,rng))
   assert ep.status=='terminal';episodes+=1
 return dict(scripted_games=episodes,model_calls=0,realized_utilities_independently_recomputed=True)

def summarize(records):
 groups={}
 for r in records:groups.setdefault(r['reset']['id'],[]).append(r)
 stats=[]
 for reset,rows in groups.items():
  for seat in range(rows[0]['reset']['players']):
   ok=[r['terminal_utility'][seat] for r in rows if r['status']=='terminal']
   complete_group=len(ok)==4 and len(rows)==4
   stats.append(dict(reset_id=reset,split=rows[0]['reset']['split'],seat=seat,observed_games=len(rows),terminal_games=len(ok),
    complete_group=complete_group,utilities=ok,utility_mean=float(np.mean(ok)) if ok else None,
    utility_std=float(np.std(ok)) if ok else None,utility_range=max(ok)-min(ok) if ok else None,
    zero_outcome_advantage=(max(ok)-min(ok)<1e-9) if complete_group else None,
    protocol_costs=[r['protocol'][seat] for r in rows]))
 return dict(games=len(records),terminal=sum(r['status']=='terminal' for r in records),
  truncated_calls=sum(c['completion']['finish_reason']=='length' for r in records for c in r['calls']),
  invalid_calls=sum(not c['valid'] for r in records for c in r['calls']),
  total_calls=sum(len(r['calls']) for r in records),
  investigations=sum(c['valid'] and c['action'].get('action')=='INVESTIGATE' for r in records for c in r['calls']),
  seat_groups=stats,reasoning_quality='Requires human review of full traces; explanation length is not a quality score.',
  generalization='Stratified development probe; not population accuracy or a heldout test result.')

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--check',action='store_true')
 p.add_argument('--learner-url');p.add_argument('--opponent-url');p.add_argument('--output',type=Path)
 a=p.parse_args()
 if a.check:print(json.dumps(check()));return
 if not(a.output and a.learner_url and a.opponent_url):p.error('Two base-model endpoints and output required')
 m,resets=load();a.output.mkdir(parents=True,exist_ok=False);(a.output/'game_calls').mkdir()
 (a.output/'manifest.json').write_text(json.dumps(dict(pack=m,prompt_version=policy_prompt.VERSION,max_tokens=1024),indent=2)+'\n')
 urls=[a.learner_url,a.opponent_url];names=['social-learner','social-base'];locks=[threading.BoundedSemaphore(16) for _ in urls]
 def run(job):
  index,reset,replica=job;ep=Episode(reset,reset['id'],replica,SEED);endpoint=index%2;error=None
  with (a.output/'game_calls'/f'{index:03d}.jsonl').open('w') as stream:
   try:
    while ep.status=='running':
     with locks[endpoint]:
      start=time.monotonic();response=complete(urls[endpoint],names[endpoint],ep.request())
      response.update(elapsed_seconds=time.monotonic()-start,endpoint_index=endpoint)
     ep.accept(response);stream.write(json.dumps(ep.calls[-1])+'\n');stream.flush()
   except Exception as exc:
    error=repr(exc);ep.status='infrastructure_or_client_failure'
    stream.write(json.dumps(dict(error=error,protocol_penalty_added=False))+'\n');stream.flush()
  return dict(ep.summary(),calls=ep.calls,error=error,job_index=index)
 jobs=[(i,r,rep) for i,(r,rep) in enumerate((r,rep) for r in resets for rep in range(4))];rows=[]
 with ThreadPoolExecutor(max_workers=32) as pool,(a.output/'games.jsonl').open('w') as stream:
  for future in as_completed([pool.submit(run,j) for j in jobs]):
   r=future.result();rows.append(r);stream.write(json.dumps(r)+'\n');stream.flush()
   print(f'Games recorded: {len(rows)}/{len(jobs)}; latest={r["status"]}',flush=True)
 summary=summarize(rows);(a.output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
 (a.output/'COMPLETE.json').write_text(json.dumps(dict(recorded=len(rows),expected=len(jobs),all_terminal=summary['terminal']==len(jobs)))+'\n')
 if any(r['error'] for r in rows):raise RuntimeError('All jobs recorded, but client/infrastructure failures occurred; inspect games.jsonl')
if __name__=='__main__':main()
