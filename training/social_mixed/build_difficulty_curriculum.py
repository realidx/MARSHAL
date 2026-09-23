"""Materialize existing certified B/O/P scenes into a shared-parent curriculum.
No auxiliary interfaces, synthetic histories, changed gold, or moved splits.
"""
import json,hashlib
from collections import Counter,defaultdict
from pathlib import Path
from training.social_mixed.reasoning_bank import load,PATH
from training.social_mixed.task_difficulty import describe,VERSION

def build():
    out=PATH/'difficulty_curriculum';out.mkdir(exist_ok=True)
    parents=defaultdict(list)
    for split in ('train','validation'):
        for t in load(split):parents[t['canonical_id']].append(t)
    records=[]
    for cid,ts in sorted(parents.items()):
        assert len(ts)==3 and len({t['split'] for t in ts})==1
        assert {t['paired_view'] for t in ts}=={'B','O','Pplus'}
        features={t['paired_view']:describe(t) for t in ts}
        tier=max(d['tier'] for d in features.values())
        records.append(dict(canonical_id=cid,split=ts[0]['split'],parent_tier=tier,
            tier_name=('foundation','intermediate','compositional')[tier],
            views={t['paired_view']:t['id'] for t in ts},view_difficulty=features,
            p_eligible=next(t for t in ts if t['paired_view']=='Pplus')['p_train_eligible'],
            teacher_policy_hashes={t['paired_view']:t['teacher'].get('policy_sha256') for t in ts}))
    (out/'parents.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in records))
    for split in ('train','validation'):
        for tier in range(3):
            selected={r['canonical_id'] for r in records if r['split']==split and r['parent_tier']==tier}
            tasks=[t for t in load(split) if t['canonical_id'] in selected]
            # Lossless task copies; not stand-alone runtime banks bypassing source manifests.
            (out/f'{split}-tier{tier}.jsonl').write_text(''.join(json.dumps(t)+'\n' for t in tasks))
    summary=dict(version=VERSION,status='structural_curriculum_requires_empirical_calibration',
        source_tasks_sha256=hashlib.sha256((PATH/'tasks.jsonl').read_bytes()).hexdigest(),
        parents=dict(Counter(r['split']+'/'+r['tier_name'] for r in records)),
        common_P_eligible_parents=dict(Counter(r['split']+'/'+r['tier_name'] for r in records if r['p_eligible'])),
        new_auxiliary_tasks=0,labels_changed=0,splits_changed=0)
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))

if __name__=='__main__':build()
