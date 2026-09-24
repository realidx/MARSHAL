"""Training-call-informed candidate; never changes active bank or validation."""
import json,collections,hashlib
from pathlib import Path
from examples.social_mixed.short_interaction_v1.audit_b_advantages import ordered,label
ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).resolve().parent
source=ROOT/'examples/social_mixed/compact_bank_200/tasks.jsonl'
tasks={t['id']:t for t in map(json.loads,source.read_text().splitlines())}
rows=[]
for tid,es in ordered.items():
 counts=[sum(label(r)=='correct' for r in rs) for rs in es]
 mixed=[any(r['task_advantage']>1e-9 for r in rs) and any(r['task_advantage']< -1e-9 for r in rs) for rs in es]
 if all(c==8 for c in counts):group='always_correct'
 elif len(es)>=3 and not any(counts):group='hard_holdout'
 elif len(es)>=3 and sum(mixed)>=2 and all(a<=b for a,b in zip(counts,counts[1:])) and counts[-1]>counts[0]:group='improving_repeated_contrast'
 elif sum(mixed)>=2 and counts[-1]>counts[0]:group='improving_limited_or_fluctuating'
 else:group='other'
 rows.append(dict(id=tid,category=group,correct=counts,mixed=mixed,operation=tasks[tid]['operation_curriculum']['B'],
  truncated=[sum(label(r)=='truncated' for r in rs) for rs in es],
  conditional_accuracy=[sum(label(r)=='correct' for r in rs)/max(1,sum(label(r) in ('correct','wrong') for r in rs)) for rs in es]))
(OUT/'task_audit.json').write_text(json.dumps(rows,indent=2)+'\n')
print('CATEGORIES',collections.Counter(r['category'] for r in rows))
for r in rows:
 if r['category'].startswith('improving'):print('LEARNABLE',r)
# Distinguish semantic progress from simply finishing more answers.
for r in rows:
 a=r['conditional_accuracy']
 r['semantic_monotone']=all(x<=y for x,y in zip(a,a[1:])) and a[-1]>a[0]
(OUT/'task_audit.json').write_text(json.dumps(rows,indent=2)+'\n')
# Freeze per-question weights, avoiding tiny-category equal-mass oversampling.
weights={'always_correct':.25,'hard_holdout':0.,'improving_repeated_contrast':2.,'improving_limited_or_fluctuating':1.5,'other':1.}
selected=[]
for r in rows:
 t=dict(tasks[r['id']]);t['b_sampling_weight']=weights[r['category']]
 if r['category']=='improving_repeated_contrast' and not r['semantic_monotone']:t['b_sampling_weight']=1.
 t['b_sampling_evidence']=r
 if t['b_sampling_weight']:selected.append(t)
(OUT/'hard_diagnostic.jsonl').write_text(''.join(json.dumps(tasks[r['id']])+'\n' for r in rows if r['category']=='hard_holdout'))
# New native B bridge: same underlying preference/goal family, no voluntary
# behavior yet and one remaining proposal. Recompute teacher; never copy gold.
from copy import deepcopy
from training.b_sft.debug.audit_readable_pretraining import reconstruct
from training.b_sft.social_private_teacher import PrivateEpisode
from training.b_sft.prepare_no_catalogue_probe import view
from training.b_sft.preference_contract import belief
from training.social_mixed.paired_requests import request
from training.social_mixed.reasoning_scoring import score
from training.b_sft.social_bp_training import native_completion
bridges={};links=[]
for r in rows:
 if r['category']!='hard_holdout':continue
 old=tasks[r['id']];inp=old['input'];raw,own=reconstruct(inp)
 raw['background_prior']=inp['background_prior'];ego=inp['player'];raw['game']['round_robin']=[p for p in range(raw['game']['n_players']) if p!=ego]+[ego]
 setup=[dict(action='PASS') for _ in range(raw['game']['n_players']-1)]
 ep=PrivateEpisode(raw,setup,seconds=20,max_nodes=30000,max_sweeps=128)
 newinp=view(ep,inp['public_preferences'],ego,own,[],setup,[])
 newinp.update(background_prior=inp['background_prior'],belief_source='history',supplied_belief=dict(known_preferences=[],unresolved_preferences=[],support='Infer from visible information.'),queries=inp['queries'],task='formation',favored_margin=.1)
 q=inp['queries'][0];mass=ep.belief(q['player'],q['goal'],observer=ego,own=own,private_results=[])['preference_weights']
 key=hashlib.sha256(json.dumps(newinp,sort_keys=True).encode()).hexdigest()
 t=deepcopy(old);t.update(id=key[:20]+'-B',canonical_id=key,source='b-learning-prior-bridge-v1',training_ready=False)
 t['input']=newinp;t['teacher']=dict(gold=belief(mass),preference_weights=mass,policy_sha256=ep.tree.certificate['policy_sha256'])
 t['canonical_action_task']=deepcopy(t);t['canonical_action_task'].pop('canonical_action_task',None)
 t['canonical_action_task']['task']='P'
 t.pop('operation_curriculum',None);t['learning_stage']='prior_without_behavior';t['b_sampling_weight']=1.
 # B does not need an action answer, but old renderer expects the legal list.
 t['input']['legal_actions']=[a.to_dict() for a in ep.tree.entries[ep.index].actions]
 t['canonical_action_task']['input']=deepcopy(t['input'])
 assert score(t,native_completion(t))['correct']
 assert 'Briefly explain' in request(t)['messages'][1]['content']
 bridges[t['id']]=t
 links.append(dict(target=old['id'],prior_bridge=t['id'],target_operation=r['operation']))
# Reuse audited training-only single-choice scenes as intermediate bridges;
# never move shared-geometry validation scenes into train.
progress=list(map(json.loads,(ROOT/'examples/social_mixed/progressive_bank_v1/tasks.jsonl').read_text().splitlines()))
intermediates=[t for t in progress if t['paired_view']=='B' and t['split']=='train' and t['learning_stage'] in ('single_choice_identifying','single_choice_uncertain') and t['id'] not in {r['id'] for r in rows if r['category'] in ('hard_holdout','always_correct')}]
for t in intermediates:
 if t['id'] not in {x['id'] for x in selected}:
  t=deepcopy(t);t['b_sampling_weight']=1.;bridges[t['id']]=t
for link in links:
 target=tasks[link['target']]
 link['single_choice_bridges']=[t['id'] for t in intermediates if t['completion_mode']==target['completion_mode']]
 link['relation']='operation-level difficulty ladder; not a same-history counterfactual pair'
# Keep the active B bank at 200: 18 deduplicated prior bridges + two
# single-choice bridges; existing retained single-choice items also remain.
prior_ids=[k for k,t in bridges.items() if t.get('learning_stage')=='prior_without_behavior']
keep=set(prior_ids)
for stage in ('single_choice_identifying','single_choice_uncertain'):
 candidates=sorted(k for k,t in bridges.items() if t.get('learning_stage')==stage)
 if candidates:keep.add(candidates[0])
reserve={k:t for k,t in bridges.items() if k not in keep}
(OUT/'bridge_reserve.jsonl').write_text(''.join(json.dumps(t)+'\n' for t in reserve.values()))
bridges={k:t for k,t in bridges.items() if k in keep}
byid={t['id']:t for t in selected};byid.update(bridges)
for link in links:link['active_single_choice_bridges']=[k for k in link['single_choice_bridges'] if k in byid]
(OUT/'bridge_links.json').write_text(json.dumps(links,indent=2)+'\n')
assert len(byid)<=200
(OUT/'train_b.jsonl').write_text(''.join(json.dumps(t)+'\n' for t in byid.values()))
(OUT/'bridge_links.json').write_text(json.dumps(links,indent=2)+'\n')
summary=dict(status='offline_candidate_not_active',original_categories=dict(collections.Counter(r['category'] for r in rows)),
 semantic_monotone_three=sum(r['category']=='improving_repeated_contrast' and r['semantic_monotone'] for r in rows),
 weights=weights,original_retained=len(selected),bridges_added=len(bridges),train_b=len(byid),
 source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),validation_changed=False)
(OUT/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print('SUMMARY',summary)
