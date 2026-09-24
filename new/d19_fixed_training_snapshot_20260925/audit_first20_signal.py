import tarfile,json,collections,math
p=tarfile.open('new/d19_fixed_training_snapshot_20260925/d0-35-878558.tar.gz');stats=collections.defaultdict(collections.Counter);errors=collections.Counter();examples={}
for n in p.getnames():
 if '/calls/step-' not in n:continue
 step=int(n.split('step-')[1].split('.')[0])
 if step>=20:continue
 rows=[json.loads(l) for l in p.extractfile(n)];groups=collections.defaultdict(list)
 for r in rows:groups[r['group']].append(r)
 for g,rs in groups.items():
  k=(rs[0]['kind'],rs[0]['training_mode']);s=stats[k];s['groups']+=1
  units={r['unit']:r for r in rs};valid=[r for r in units.values() if r['score']['status']!='format_failure' and r['completion']['finish_reason']!='length' and r['score'].get('semantic_eligible',True)]
  vs=[r['score']['reward'] for r in valid];mean=sum(vs)/len(vs) if vs else 0;std=(sum((v-mean)**2 for v in vs)/len(vs))**.5 if vs else 0
  s['active_groups']+=std>1e-9
  for r in rs:
   ok=r['unit'] in {v['unit'] for v in valid};expected=(r['score']['reward']-mean)/(std+1e-6) if ok else 0
   errors['advantage_mismatch']+=abs(expected-r['task_advantage'])>1e-6
   errors['sum_mismatch']+=abs(r['advantage']-r['task_advantage']-r['protocol_advantage'])>1e-6
   errors['token_logprob_mismatch']+=len(r['response_ids'])!=len(r['behavior_log_probs'])
   errors['weight_mismatch']+=abs(r['loss_weight']-len(rows)/3/4/8/r['trajectory_length'])>1e-6
   s['rows']+=1;s['tokens']+=len(r['response_ids']);s['truncated']+=r['completion']['finish_reason']=='length';s['positive_rows']+=r['task_advantage']>0;s['negative_rows']+=r['task_advantage']<0;s['correct']+=r['score'].get('correct') is True
   s['weighted_abs_task']+=abs(r['task_advantage'])*r['loss_weight']/len(rows);s['weighted_abs_protocol']+=abs(r['protocol_advantage'])*r['loss_weight']/len(rows)
   s['masked']+=r['score'].get('semantic_outcome')=='masked'
  if k[1]=='short_interaction':
   s['trajectories']+=len(units);s['terminal']+=len(valid);s['negative_terminal']+=sum(v<0 for v in vs)
   s['terminal_positive_adv_nonpositive_payoff']+=sum(r['task_advantage']>0 and r['score']['reward']<=0 for r in valid)
   for r in valid:
    if r['task_advantage']>0 and r['score']['reward']<=0:examples.setdefault('positive_adv_nonpositive',dict(step=step,task=r['task_id'],reward=r['score']['reward'],adv=r['task_advantage'],group_rewards=vs))
print(json.dumps({'stats':{str(k):dict(v) for k,v in stats.items()},'errors':dict(errors),'examples':examples},indent=2))
