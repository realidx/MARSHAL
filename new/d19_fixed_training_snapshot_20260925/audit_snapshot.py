import tarfile,json,collections,statistics,jsonschema
p=tarfile.open('new/d19_fixed_training_snapshot_20260925/d0-35-878558.tar.gz');out=collections.defaultdict(collections.Counter);groups=collections.defaultdict(list)
for n in p.getnames():
 if not n.startswith('./calls/') or not n.endswith('jsonl'):continue
 step=int(n.split('step-')[1].split('.')[0]);period='0-9' if step<10 else '10-19' if step<20 else '20-35'
 for l in p.extractfile(n):
  r=json.loads(l);key=(period,r['kind'],r.get('training_mode'));c=out[key];c['calls']+=1;c['correct']+=r['score'].get('correct') is True;c['truncated']+=r['completion']['finish_reason']=='length';c['invalid']+=r.get('protocol_failure')=='invalid_action';c['tokens']+=len(r['response_ids']);groups[(key,r['group'])].append(r)
  if r.get('protocol_failure')=='invalid_action':
   try:
    f=r['completion']['raw_message']['tool_calls'];assert len(f)==1;f=f[0]['function'];schema=next(t['function']['parameters'] for t in r['request']['tools'] if t['function']['name']==f['name']);jsonschema.validate(json.loads(f['arguments']),schema);c['invalid_but_schema_valid']+=1
   except Exception:pass
for (key,g),rs in groups.items():
 c=out[key];c['groups']+=1;c['active']+=any(abs(r['task_advantage'])>1e-8 for r in rs)
 if key[2]=='short_interaction':
  units={r['unit']:r for r in rs};c['trajectories']+=len(units);v=[r for r in units.values() if r['score']['status']=='ok'];c['terminal']+=len(v);c['utility_sum']+=sum(r['score']['reward'] for r in v)
for k,v in sorted(out.items()):print(k,dict(v))
rs=[json.loads(l) for l in p.extractfile('./metrics.jsonl')];print('metrics',len(rs))
for key in ['actor_train/grad_norm','actor/clip_fraction','actor/applied_lr','behavior_preupdate_clip_fraction','actor/kl_weighted']:
 vals=[r[key] for r in rs if key in r];print(key,min(vals),max(vals),vals[0],vals[-1])
