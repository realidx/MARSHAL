"""Export request review and linked P4 coverage after offline construction."""
import json,hashlib
from pathlib import Path
from training.social_mixed.prepare_distribution_curriculum import OUT,ROOT,read,sha,PROFILES,annotate
from training.b_sft.social_named_probe import request
from training.social_mixed.core import Episode

def main():
 m=json.loads((OUT/'manifest.json').read_text())
 for name in ('bp_train.jsonl','bp_validation.jsonl','diagnostics.jsonl'):
  rows=[annotate(t) for t in read(OUT/name)]
  (OUT/name).write_text(''.join(json.dumps(t,ensure_ascii=False)+'\n' for t in rows))
 for name in ('selfplay_train.jsonl','selfplay_validation.jsonl'):
  rows=read(OUT/name)
  for t in rows:
   t['geometry_source_id']=t['id'].rsplit(':',1)[0]
   if 'generation' in t:t['geometry_generation']=t.pop('generation')
  (OUT/name).write_text(''.join(json.dumps(t,ensure_ascii=False)+'\n' for t in rows))
 (OUT/'requests_train.jsonl').write_text(''.join(json.dumps(dict(id=t['id'],request=request(t,'action_tools',t.get('name_variant',0))),ensure_ascii=False)+'\n' for t in read(OUT/'bp_train.jsonl')))
 for n in m['files']:
  b=(OUT/n).read_bytes();m['files'][n]=dict(count=len(b.splitlines()),sha256=sha(b))
 sources=['training/b_sft/preference_contract.py','training/b_sft/review_prompt.py','training/b_sft/social_prompt.py','training/b_sft/social_named_probe.py','training/b_sft/social_private_teacher.py','training/b_sft/decision_policy.py','training/b_sft/social_p_qualitative.py','training/social_mixed/policy_prompt.py','training/social_mixed/weighted_rules.py','training/social_mixed/distribution_sampling.py','training/social_mixed/frozen/bp_display.py','training/social_mixed/frozen/selfplay_prompt.py']
 m['prompt_sources']={n:sha((ROOT/n).read_bytes()) for n in sources}
 bp=read(OUT/'bp_train.jsonl');diag=read(OUT/'diagnostics.jsonl');by={(t['origin_id'],t['background_profile']):t for t in bp+diag}
 links=[]
 for base in read(ROOT/'examples/social_bp/p4_information_core_v1/acquisition_use_links.jsonl'):
  for profile in PROFILES:
   parent=by[base['parent'],profile];children=[by[c,profile] for c in base['children']]
   assert len({t['teacher']['policy_sha256'] for t in [parent]+children})==1
   assert len({json.dumps(t['input']['current_state'],sort_keys=True) for t in children})==1
   links.append(dict(profile=profile,mode=base['scoring'],parent=parent['id'],children=[t['id'] for t in children],diagnostic_children=[t['id'] for t in children if t['diagnostic_only']],same_selected_policy=True))
 (OUT/'p4_links.json').write_text(json.dumps(links,indent=2)+'\n')
 m.update(formal_mixed_training_ready=True,coverage='All B1-B3/P1-P4 training kernels; 4 backgrounds. Six impossible B3 history/profile combinations excluded with reasons; no model-score selection.',diagnostic_count=len(diag))
 (OUT/'manifest.json').write_text(json.dumps(m,indent=2)+'\n')
 chosen=[]
 for k in ('B1','B2','B3','P1','P2','P3','P4'):
  for p in PROFILES:
   choices=[t for t in bp if t['kernel']==k and t['background_profile']==p];chosen.append(choices[0])
 chosen += [t for t in bp if t['kernel']=='P4' and t['background_profile']=='balanced']
 chosen=list({t['id']:t for t in chosen}.values())
 cards=['# B/P 新分布与容差：实际请求审阅样例','标题的内核和profile不发送给模型。全部训练请求见requests_train.jsonl。','']
 for t in chosen:
  cards += [f'## {t["kernel"]} / {t["background_profile"]} / {t["id"]}']
  cards += [msg['role'].upper()+'\n\n'+msg['content']+'\n' for msg in request(t,'action_tools',t.get('name_variant',0))['messages']]
 (OUT/'bp_review.md').write_text('\n'.join(cards))
 cards=['# Self-play：实际请求审阅样例','']
 sp=read(OUT/'selfplay_train.jsonl')
 for profile in PROFILES:
  r=next(r for r in sp if r['background_profile']==profile);ep=Episode(r,r['id'],0,42)
  cards += [f'## {profile} / {r["id"]}']+[msg['role'].upper()+'\n\n'+msg['content']+'\n' for msg in ep.request()['messages']]
 (OUT/'selfplay_review.md').write_text('\n'.join(cards));print('P4 linked units:',len(links),'BP review examples:',len(chosen))
if __name__=='__main__':main()
