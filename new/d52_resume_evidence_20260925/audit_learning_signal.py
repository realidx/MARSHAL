import tarfile,json,collections,statistics
from training.social_mixed.reasoning_scoring import score
from training.social_mixed.reasoning_training import group_advantages
bank={r['id']:r for r in map(json.loads,open('examples/social_mixed/interaction_bank_v1/tasks.jsonl'))}
t=tarfile.open('new/d52_resume_evidence_20260925/training/d52-878181.tar.gz');groups=collections.defaultdict(list)
for n in t.getnames():
 if n.startswith('./calls/'):
  for l in t.extractfile(n):
   r=json.loads(l);groups[r['group']].append(r)
c=collections.defaultdict(collections.Counter)
for g,rs in groups.items():
 kind=rs[0]['kind'];short=rs[0].get('training_mode')=='short_interaction';period='26-38' if int(g.split(':')[0])<=38 else '39-52';v=c[(kind,'short' if short else 'static',period)];v['groups']+=1;v['old_active']+=any(abs(r['task_advantage'])>1e-8 for r in rs)
 if short:
  units={r['unit']:r for r in rs};valid=[r for r in units.values() if r['score']['status']=='ok'];v['trajectories']+=len(units);v['terminal']+=len(valid);v['positive_trajectories']+=sum(r['task_advantage']>1e-8 for r in valid);v['utility_sum']+=sum(r['score']['reward'] for r in valid);continue
 new=[score(dict(bank[r['task_id']],name_variant=0),r['completion']) for r in rs];adv,_=group_advantages(new,rs,'standard_sequence');v['new_active']+=any(abs(a)>1e-8 for a in adv);v['truncated']+=sum(r['finish_reason']=='length' for r in rs);v['positive_old']+=sum(r['task_advantage']>1e-8 for r in rs);v['positive_new']+=sum(a>1e-8 for a in adv);v['correct_new']+=sum(s.get('correct') is True for s in new);v['calls']+=len(rs)
 v['all_valid_correct_with_truncation']+=any(r['finish_reason']=='length' for r in rs) and any(s['status']=='ok' for s in new) and all(s.get('correct') for s in new if s['status']=='ok')
for k,v in c.items():print(k,dict(v))
