"""One focal LLM versus one exact or bounded reference player, both seat assignments."""
import argparse,json,hashlib
from pathlib import Path
from examples.final_evaluation.team_benac import load,digest,complete
from examples.final_evaluation.team_oracle import Controller
from examples.final_evaluation.adversarial_runtime import play

def main():
 p=argparse.ArgumentParser()
 for k in ('suite','output'):p.add_argument('--'+k,type=Path,required=True)
 for k in ('base-url','model','checkpoint-hash'):p.add_argument('--'+k,required=True)
 p.add_argument('--policies',type=Path);p.add_argument('--reference',choices=['exact','bounded'],default='exact')
 p.add_argument('--batch-invariant-confirmed',action='store_true');a=p.parse_args()
 if not a.batch_invariant_confirmed:p.error('Confirm batch-invariant service')
 m,resets=load(a.suite)
 if a.reference=='exact':
  if a.policies is None:p.error('--policies required for exact reference')
  report=json.loads((a.policies/'preflight.json').read_text())
  if not report['ready'] or report['suite_manifest_sha256']!=digest(a.suite/'manifest.json'):raise ValueError('Need complete, matching reference preflight')
  records={r['case_id']:r for r in report['cases']};policies={}
  for r in resets:
   record=records[r['id']];path=a.policies/record['file']
   if digest(path)!=record['sha256']:raise ValueError('Changed reference file')
   policy=json.loads(path.read_text())
   if policy['reset_sha256']!=hashlib.sha256(json.dumps(r,sort_keys=True).encode()).hexdigest():raise ValueError('Changed reset')
   policies[r['id']]=policy
 else:
  from examples.final_evaluation.bounded_reference import BoundedController,SPEC
  report=SPEC
 a.output.mkdir(parents=True,exist_ok=False);route=dict(base_url=a.base_url,model=a.model)
 (a.output/'protocol.json').write_text(json.dumps(dict(suite=m,reference_preflight=report,reference_kind=a.reference,reference_source_sha256=digest(Path(__file__).with_name('bounded_reference.py' if a.reference=='bounded' else 'team_oracle.py')),route=route,checkpoint_hash=a.checkpoint_hash,seats=[0,1],repeats=1,temperature=0,max_tokens=1024,batch_invariant_operator_confirmed=True),indent=2))
 rows=[]
 for reset in resets:
  for seat in (0,1):
   rows+=play(reset,seat,0,dict(q0=route,focal=route),a.output,complete,oracle=(Controller(policies[reset['id']],seat,2026092601) if a.reference=='exact' else BoundedController(reset,seat,2026092601)))
   (a.output/'results.json').write_text(json.dumps(rows,indent=2))
   if rows[-1]['status']=='infrastructure_failure':raise RuntimeError('Infrastructure failure; see raw log')
 done=[r for r in rows if r['status']=='terminal']
 summary=dict(games=len(rows),completed=len(done),conditional_focal_utility=sum(r['focal_utility'] for r in done)/len(done) if done else None,conditional_team_utility=sum(r['total_utility'] for r in done)/len(done) if done else None,full_cohort_focal_bounds=[sum(r['missing_utility_bounds'][k] for r in rows)/len(rows) for k in ('lower','upper')],invalid_calls=sum(r['focal_invalid_calls'] for r in rows),truncated_calls=sum(r['focal_truncated_calls'] for r in rows))
 (a.output/'summary.json').write_text(json.dumps(summary,indent=2));(a.output/'COMPLETE.json').write_text(json.dumps(dict(games=len(rows))))
if __name__=='__main__':main()
