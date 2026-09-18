"""Freeze v4 plus audited prerequisites and explicit practice quotas."""
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
from training.social_mixed.prepare_reasoning_v4 import OUT as SOURCE, read
from training.social_mixed.core import ROOT
from training.social_mixed.audit_zero_signal import OUT as BRIDGES, interface_check, cell
from training.social_mixed.curriculum_sampling import VERSION
from training.social_mixed.prompt_clarification import request, VERSION as PROMPT_VERSION
from training.social_mixed.structure_coverage import audit
from training.social_mixed.prepare_reasoning_v4 import digest, stable

OUT = ROOT/'examples/social_mixed/data_reasoning_v5_candidate'


def write(name, rows):
    (OUT/name).write_text(''.join(json.dumps(t)+'\n' for t in rows))


def main():
    OUT.mkdir(exist_ok=True)
    for p in SOURCE.glob('*.jsonl'):
        shutil.copyfile(p, OUT/p.name)
    train=read(OUT/'bp_train.jsonl')
    baseline_ids={t['id'] for t in train}
    for split in ('train','validation'):
        additions=read(OUT/('linear_history_'+split+'.jsonl'))
        extra=[]
        for t in additions:
            assert interface_check(t,request_builder=request)['all_passed']
            t['linear_history_addition']=True
            t['periodic_validation']=False
            if t['task']!='P':continue
            t['contrast_group']='linear-v5:'+t['id'];t['p123_case']=t['contrast_group']
            oracle=deepcopy(t);oracle['id']=digest(['oracle-pair',t['id']]);oracle['native_task_id']=oracle['id'];oracle['oracle_pair_of']=t['id']
            oracle['input']['belief_source']='supplied'
            names={1:'want',0:'neutral',-1:'avoid'}
            oracle['input']['supplied_belief']=dict(known_preferences=[],unresolved_preferences=[],
                support='This is YOUR supplied exact joint distribution. This joint posterior follows from the same visible history under the stated partner policy; it does not disclose the realized hidden world.',
                joint_distribution=[dict(probability=str(float(w)),preferences=[dict(player=p,goal=g,preference=names[v]) for p,row in enumerate(world) for g,v in enumerate(row)]) for world,w in zip(t['teacher']['worlds'],t['teacher']['posterior']) if w>0])
            oracle['semantic_id']=digest(oracle['input']);extra.append(oracle)
        if split=='train':train.extend(additions+extra)
        else:
            dev=read(OUT/'bp_validation.jsonl')+additions+extra
            for t in dev:t['prompt_clarification']=PROMPT_VERSION
            # Substitute an intact linear B/raw-P/oracle-P triple into the fixed
            # 45-task panel; preserve all previously covered diagnostic cells.
            from itertools import combinations
            from collections import defaultdict
            from training.social_mixed.validation import cells
            panel=[t for t in dev if t.get('periodic_validation')]
            required={c for t in panel for c in cells(t)}
            raw=next(t for t in additions if t['task']=='P')
            triple=[raw,next(t for t in additions if t['id']==raw['linked_b_id']),next(t for t in extra if t['oracle_pair_of']==raw['id'])]
            units=defaultdict(list)
            for t in panel:units[(t['kernel'],t.get('contrast_group'),t['completion_mode'],t['background_profile'])].append(t)
            choices=list(units.values());replacement=None
            for n in range(1,5):
                for removed in combinations(choices,n):
                    ids={t['id'] for u in removed for t in u}
                    proposal=[t for t in panel if t['id'] not in ids]+triple
                    if len(proposal)==len(panel) and required<={c for t in proposal for c in cells(t)}:
                        replacement=proposal;break
                if replacement is not None:break
            if replacement is None:raise ValueError('Cannot preserve fixed validation coverage')
            panel_ids={t['id'] for t in replacement}
            for t in dev:t['periodic_validation']=t['id'] in panel_ids
            write('bp_validation.jsonl',dev)
            write('requests_validation.jsonl',[dict(id=t['id'],request=request(t,'action_tools',t.get('name_variant',0))) for t in dev])
    bridges=read(BRIDGES/'bridge_candidates.jsonl')
    for original in bridges:
        t=deepcopy(original)
        assert interface_check(t)['all_passed']
        t.update(training_ready=True,review_status='cpu_verified_prerequisite_no_learning_claim')
        train.append(t)
    by={t['id']:t for t in train}
    assert len(by)==len(train)
    for t in train:
        t['prompt_clarification']=PROMPT_VERSION
        t['sampling_version']=VERSION
        t['sampling_baseline']=t['id'] in baseline_ids
        t['practice_units']={}
        if t.get('bridge_stage'):
            t['practice_units']['bridge']=t['bridge_stage']
        if cell(t) and t['task']=='B':
            # Preserve hard examples while redistributing exposure inside the
            # frozen v4 task-count budget.
            t['practice_units']['reduced']=t['origin_id']
        if t.get('reasoning_source_id') and t['task']=='P' and t['skill']=='result_use':
            t['practice_units']['result']=t['contrast_group']
    for t in train:
        if t['task']=='P' and t['teacher'].get('history_changes_acceptable') and not t.get('oracle_pair_of'):
            members=[t,by[t['linked_b_id']]]+[o for o in train if o.get('oracle_pair_of')==t['id']]
            assert len(members)==3
            for member in members:
                member['practice_units']['history']=t['id']
    write('bp_train.jsonl',train)
    write('requests_train.jsonl',[dict(id=t['id'],request=request(t,'action_tools',t.get('name_variant',0))) for t in train])
    sp=read(OUT/'selfplay_train.jsonl')
    for t in sp:
        t['sampling_version']=VERSION
        t['prompt_clarification']=PROMPT_VERSION
    write('selfplay_train.jsonl',sp)
    spdev=read(OUT/'selfplay_validation.jsonl')
    for t in spdev:t['prompt_clarification']=PROMPT_VERSION
    write('selfplay_validation.jsonl',spdev)
    report=audit(OUT)
    assert not report['cross_split_families']
    (OUT/'structure_audit.json').write_text(json.dumps(report,indent=2))
    manifest=json.loads((SOURCE/'manifest.json').read_text())
    prompt_path='training/social_mixed/prompt_clarification.py'
    manifest['prompt_sources'][prompt_path]=hashlib.sha256((ROOT/prompt_path).read_bytes()).hexdigest()
    manifest.update(dataset_version=VERSION+'-candidate',active=False,model_calls=0,
        parent_manifest_sha256=hashlib.sha256((SOURCE/'manifest.json').read_bytes()).hexdigest(),
        sampling=dict(bp='Intact practice and regular units replace each other under each original v4 step task-count cap; no extra task groups',
                      sp='Proposal-slot tiers <=6 / 7–9 / >=10 at 50% / 25% / 25% reset admissions; not token or gradient shares'),
        files={p.name:dict(count=len(p.read_text().splitlines()),sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in OUT.glob('*.jsonl')})
    manifest['coverage']['bp_train']=dict(Counter(t['kernel'] for t in train))
    manifest['coverage']['bp_validation']=dict(Counter(t['kernel'] for t in dev))
    manifest['mode_counts']['bp_train']=dict(Counter(t['completion_mode'] for t in train))
    manifest['mode_counts']['bp_validation']=dict(Counter(t['completion_mode'] for t in dev))
    manifest['periodic_validation_ids']=sorted(panel_ids)
    for name in ('prepare_reasoning_v5.py','search_linear_history_v5.py','audit_reasoning_v5.py','curriculum_sampling.py','distribution_sampling.py','core.py'):
        rel='training/social_mixed/'+name
        manifest['construction_sources'][rel]=hashlib.sha256((ROOT/rel).read_bytes()).hexdigest()
    manifest['limitations']=[s for s in manifest['limitations'] if 'balanced-prior' not in s]+[
        'Prerequisite and exposure changes are hypotheses, not demonstrated learning improvements.',
        'Per-step task count is bounded by v4, but actual completion token lengths remain model-dependent.',
        'Long-game failures and terminal-outcome masking are not repaired by horizon reweighting.',
        'Test unchanged; dev includes independent linear history additions with a fixed 45-task panel; no new held-out prerequisite evaluation was added.']
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(dict(bp_train=len(train),sp_train=len(sp),bridges=len(bridges),active=False)))


if __name__=='__main__':main()
