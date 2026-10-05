"""Unify terminal entry distributions and longer-parent singleton neighborhoods."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import shutil
import numpy as np
from training.b_sft.preference_contract import world_weights
from training.b_sft.social_private_teacher import PrivateInvestigationRules
from training.strategic_slices.build import structural_family
from training.strategic_slices.common import digest, file_hash, write_json, write_rows
from training.strategic_slices.terminal_candidates import VERSION, restore_reference, TerminalCandidates
from training.strategic_slices.behavior_information import public_behavior_value
from training.strategic_slices.values import window_values
from new.benac_slice_pilot.metrics import masked_answer_value


def read_rows(path):
    return [json.loads(x) for x in path.read_text().splitlines()]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--entry-source',type=Path,action='append')
    p.add_argument('--late-source',type=Path,default=Path('new/local_data/strategic_slices_terminal_entry_fresh_v1'))
    p.add_argument('--control-source',type=Path,default=Path('new/local_data/strategic_slices_terminal_entry_pilot_v3'))
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.entry_source=a.entry_source or [Path('new/local_data/strategic_slices_terminal_entry_candidates_v5')];out=a.output;out.mkdir(parents=True,exist_ok=False);(out/'references').mkdir()
    parents={};references={};rows=[];ledger=[];pending={};source_hashes={}
    def reference(parent,certificate,history,path,regime):
        rid=digest((parent['id'],history,certificate['policy_sha256']))[:24]
        if rid not in references:
            destination=f'references/{rid}.npz';shutil.copyfile(path,out/destination)
            rules=PrivateInvestigationRules(parent['raw'])
            references[rid]=dict(id=rid,parent_id=parent['id'],history=history,certificate=certificate,
                file=destination,sha256=file_hash(out/destination),world_weights=world_weights(rules.worlds,parent['raw']['background_prior']).tolist(),
                belief_regime=regime)
        return rid
    for source in a.entry_source:
        source_hashes[str(source/'manifest.json')]=file_hash(source/'manifest.json')
        for split in ('train','validation','test'):
            for parent in read_rows(source/f'{split}_parents.jsonl'):
                parents[parent['id']]=parent
            for old in read_rows(source/f'{split}_entry_sets.jsonl'):
                parent=parents[old['parent_id']]
                rid=reference(parent,parent['certificate'],[],source/parent['reference_file'],'initial-prior-plus-reference-reach')
                members=[dict(m) for m in old['members']]
                for member in members:member['history_encoding']='native-action-dicts'
                rows.append(dict(id=old['id'],parent_id=parent['id'],family=parent['family'],reference_id=rid,
                    ego=old['ego'],k=old['k'],V_star=old['V_star'],V_min=old['V_min'],C_span=old['C_span'],members=members,
                    entry_kind='reference-reach-entry-set',information_scope='collective-entry-distribution',
                    information_channels=dict(query_answer=None,future_public_history=None,entry_and_future_public_history=old['S_entry_history']),
                    group_reach_probability=old['group_reach_probability'],source=str(source),source_id=old['id']))
    for source,controls in ((a.late_source,False),(a.control_source,True)):
        source_hashes[str(source/'summary.json')]=file_hash(source/'summary.json')
        cases=json.loads((source/'cases.json').read_text());records=json.loads((source/'summary.json').read_text())['results']
        for i,record in enumerate(records):
            case=cases[i]
            # All certified cases of the two designed investigation parents, not just positive rows.
            if controls and case['origin']['kind']!='source-derived-information-acquisition':continue
            if record['status']!='certified':
                ledger.append(dict(source=str(source),index=i,status=record['status'],oracle_label=None));continue
            pid=case['parent_id'];raw=case['raw']
            assert pid in (digest(raw)[:24],digest({key:value for key,value in raw.items() if key not in ('slice_setup_histories','generation')})[:24])
            if pid not in parents:
                parents[pid]=dict(id=pid,raw=raw,family=structural_family(raw['game']),players=raw['game']['n_players'],
                    origin=case['origin'],calibration_family=controls)
            parent=parents[pid]
            rid=reference(parent,record['certificate'],case['history'],source/f'reference_{i}.npz','world-independent-public-prefix')
            for old in record['slices']:
                metric=next(m for m in old['length_curve'] if m['k']==old['k'])
                weights=old['entry_world_weights'];s=max((x['S'] for x in old['information_values']),default=0.)
                member=dict(root_index=0,history=case['history'],history_encoding='native-action-indices',probability=1.,
                    world_weights=weights,joint_world_masses=weights,remaining_proposals=case['remaining'],
                    **{key:metric[key] for key in ('V_star','V_min','C_span','root_Q')})
                row=dict(id=digest((rid,old['id']))[:24],parent_id=pid,family=parent['family'],reference_id=rid,
                    ego=old['ego'],k=old['k'],V_star=metric['V_star'],V_min=metric['V_min'],C_span=metric['C_span'],members=[member],
                    entry_kind='late-singleton',information_scope='one-entrance-conditioned-on-own-information',
                    information_channels=dict(query_answer=s,future_public_history=None,entry_and_future_public_history=None),
                    query_details=old['information_values'],group_reach_probability=None,source=str(source),source_id=old['id'],
                    entrance_features={key:case.get(key) for key in ('sampling','commitment_stratum','informative_query_available','repeated_focal_proposal','potential_later_response')})
                rows.append(row);pending[row['id']]=row
    # Keep 8 windows/parent; for late neighborhoods cover remaining depth and own k
    # before taking a second example from the same depth/k stratum.
    by_parent=defaultdict(list)
    for row in rows:by_parent[row['parent_id']].append(row)
    selected=[]
    def information(row):return max((v for v in row['information_channels'].values() if v is not None),default=0.)
    for pid,pool in by_parent.items():
        if all(r['entry_kind']=='reference-reach-entry-set' for r in pool):selected.extend(pool);continue
        pool.sort(key=lambda r:(-round(information(r),8),r['k'],r['id']))
        chosen=[];strata=set()
        for row in pool:
            key=(row['members'][0]['remaining_proposals'],row['k'])
            if key not in strata:chosen.append(row);strata.add(key)
            if len(chosen)==8:break
        ids={r['id'] for r in chosen}
        chosen.extend(r for r in pool if r['id'] not in ids)
        selected.extend(chosen[:8])
        ledger.append(dict(parent_id=pid,eligible_before_cap=len(pool),retained=min(8,len(pool)),status='parent_cap'))
    # Apply the same family parent cap before expensive selected-row diagnostics.
    family_parents=defaultdict(list)
    for pid in {r['parent_id'] for r in selected}:family_parents[parents[pid]['family']].append(pid)
    keep=set()
    for family,ids in family_parents.items():
        keep.update(sorted(ids,key=lambda pid:(not parents[pid].get('calibration_family',False),pid))[:8])
    selected=[r for r in selected if r['parent_id'] in keep];parents={pid:p for pid,p in parents.items() if pid in keep}
    for rid, group in __import__('itertools').groupby(sorted((r for r in selected if r['id'] in pending),key=lambda r:r['reference_id']),key=lambda r:r['reference_id']):
        group=list(group);ref=references[rid];tree=restore_reference(parents[ref['parent_id']]['raw'],ref,out/ref['file'])
        for row in group:
            member=row['members'][0];weights=member['world_weights'];ego=row['ego'];k=row['k']
            metric=window_values(tree,ego,0,weights,k)
            assert all(abs(metric[key]-row[key])<1e-7 for key in ('V_star','V_min','C_span'))
            for detail in row['query_details']:
                result=masked_answer_value(tree,ego=ego,root_index=0,root_weights=weights,query_slot=tuple(detail['slot']),k=k)
                assert abs(result['S']-detail['S'])<1e-7
            behavior=public_behavior_value(tree,ego=ego,root_index=0,root_weights=weights,k=k,seconds=10)
            row['information_channels']['future_public_history']=behavior['S']
            row['future_history_diagnostic']=behavior
        print('verified late reference',rid,len(group),flush=True)
    # Reassign families before D; calibration families are train only.
    families=defaultdict(list)
    for p in parents.values():families[p['family']].append(p['id'])
    calibration={p['family'] for p in parents.values() if p.get('calibration_family',False)}
    targets=dict(train=len(parents)*.625,validation=len(parents)*.125,test=len(parents)*.25)
    mapping={f:'train' for f in calibration};assigned=Counter(train=sum(len(families[f]) for f in calibration))
    for family in sorted(families,key=lambda f:(-len(families[f]),digest((20261004,f)))):
        if family not in mapping:
            split=max(targets,key=lambda s:targets[s]-assigned[s]);mapping[family]=split;assigned[split]+=len(families[family])
    for row in list(parents.values())+selected:
        row['split']=mapping[row['family']];row['calibration_family']=row['family'] in calibration
    for row in selected:
        row['information_positive']=information(row)>.05
        row['detectable_information_value']=information(row)>1e-6
    used={r['reference_id'] for r in selected};references={rid:r for rid,r in references.items() if rid in used}
    for path in (out/'references').glob('*.npz'):
        if path.stem not in used:path.unlink()
    # No stale source-format reference paths on normalized parents.
    for parent in parents.values():
        for key in ('reference_file','reference_sha256','certificate','native_audit'):parent.pop(key,None)
    write_rows(out/'parents.jsonl',list(parents.values()));write_rows(out/'references.jsonl',list(references.values()))
    write_rows(out/'candidates.jsonl',selected);write_json(out/'ledger.json',ledger)
    manifest=dict(version=VERSION,status='candidate-review-only',training_compatible=False,D_measured=False,
        parents=len(parents),families=len(families),candidates=len(selected),references=len(references),
        source_sha256=source_hashes,selection=dict(min_C=.1,min_increment=.05,min_S=.05,max_per_parent=8,max_parents_per_family=8,
        future_history='Diagnostic after source selection; not an exhaustive search for future-history-positive rows'),
        entry_kinds=dict(Counter(r['entry_kind'] for r in selected)),
        information_positive=sum(r['information_positive'] for r in selected),
        detectable_information_value=sum(r['detectable_information_value'] for r in selected),
        information_contract='Separate named channels. Null means unmeasured. Never add channels or copy collective S to individual histories.',
        belief_contract='Initial-root equilibrium/reference-reach entry sets and exogenously sampled late-root equilibria are distinct strata; neither asserts the late reference is a restriction of an initial-game equilibrium.',
        splits={s:dict(parents=sum(p['split']==s for p in parents.values()),candidates=sum(r['split']==s for r in selected)) for s in targets},
        files={str(f.relative_to(out)):file_hash(f) for f in out.rglob('*') if f.is_file()})
    write_json(out/'manifest.json',manifest)
    dataset=TerminalCandidates(out)
    write_json(out/'audit.json',dataset.audit_values())
    print({k:v for k,v in manifest.items() if k!='files'},flush=True)

if __name__=='__main__':main()
