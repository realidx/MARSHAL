"""Evidence-backed shortlist, deliberately not a train-ready release."""
import json,tarfile,hashlib
from pathlib import Path
from training.b_sft.social_bp_training import reward
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).parent
read=lambda p:[json.loads(l) for l in (ROOT/p).read_text().splitlines()]
sources={'paired':('examples/social_mixed/paired_bank_v2/tasks.jsonl','new_D'),'old':('examples/social_mixed/data_reasoning_v5_candidate/bp_train.jsonl','old_BP_main')}
choices={'e5f61bb093b9a74ba1af-O':('paired','O'),'0c1b45de0c673e8ed02b-O':('paired','O'),'1bdcb7f2424f2c336d94':('old','P'),'93cdfb603f59274df229':('old','P')}
rows={};examples={};inventory=[]
for cohort,(path,audit) in sources.items():
 bank={r['id']:r for r in read(path)};evidence={r['task_id']:r for r in read('new/task_learning_audit_20260924/'+audit+'.jsonl')}
 for tid,t in bank.items():
  if t['split']!='train' or t['input']['game']['n_players']!=3 or t.get('paired_view',t['task']) not in ('O','P'):continue
  legal={a['partner_id'] for a in t['input'].get('legal_actions',[]) if a.get('action')=='OFFER'}
  if len(legal)<2:continue
  inventory.append(dict(id=tid,cohort=cohort,origin=t.get('origin_id'),legal_partners=sorted(legal),acceptable=t['teacher']['acceptable_actions'],counts=evidence.get(tid,{}).get('counts')))
 for tid,(c,kind) in choices.items():
  if c!=cohort:continue
  t=bank[tid];e=evidence[tid];assert e['counts'].get('correct',0)>0 and e['counts'].get('wrong',0)>0
  rows[tid]=dict(id=tid,task=t,evidence=dict(e,source_cohort=c),kind=kind,scorer='training.b_sft.social_bp_training.reward',status='candidate_only_partner_identity_confounded')
archives=['new/old_bp_full_training_calls_20260924/860494-steps-0-102.tar.gz','new/old_bp_full_training_calls_20260924/861241-steps-100-205.tar.gz','new/d_evidence_20260924/training/d0-72-874127.tar.gz','new/d_evidence_20260924/training/d72-148-875169.tar.gz']
checks=0
for a in archives:
 with tarfile.open(ROOT/a) as tar:
  for m in tar:
   if 'calls/step-' not in m.name or not m.name.endswith('.jsonl'):continue
   step=int(m.name.split('step-')[1].split('.')[0])
   if '860494' in a and step>99:continue
   for l in tar.extractfile(m):
    r=json.loads(l);tid=r['task_id']
    if tid not in rows:continue
    req=dict(r['request']);req.pop('seed',None);req.pop('model',None)
    if 'request' in rows[tid]:assert req==rows[tid]['request']
    rows[tid]['request']=req;s=reward(rows[tid]['task'],r['completion']);assert s['correct']==r['score']['correct'];checks+=1
    examples.setdefault((tid,bool(s['correct'])),dict(task_id=tid,step=step,archive=a,completion=r['completion'],score=s))
for r in rows.values():assert 'request' in r
for name,data in [('candidates.jsonl',rows.values()),('examples.jsonl',examples.values()),('inventory.jsonl',inventory)]:
 (OUT/name).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in data))
(OUT/'audit.json').write_text(json.dumps(dict(status='not_train_ready',calls_rescored=checks,selected=4,independent_origins=2,all_candidates_correct_partner=1,missing='Outcome-relevant choice of different partner; relabeling players alone is not a new reasoning structure',original_micro24_sha256=hashlib.sha256((ROOT/'examples/social_mixed/micro_learning_24_v1/tasks.jsonl').read_bytes()).hexdigest()),indent=2)+'\n')
print(checks)
