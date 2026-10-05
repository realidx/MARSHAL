"""Freeze and independently audit 100 parents with multiple oracle-reach slices."""
import argparse
from collections import Counter,defaultdict
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import numpy as np
from training.strategic_slices.common import digest,file_hash,write_json,write_rows,stable
from training.strategic_slices.oracle_consistent import CONTRACT,prefix_joint_mass,canonical_parent
from training.strategic_slices.terminal_candidates import VERSION,TerminalCandidates
from training.strategic_slices.equilibrium import certify_policy
from training.strategic_slices.values import window_values,masked_answer_value
from training.strategic_slices.behavior_information import public_history_value


def selection(source):
    jobs=json.loads((source/'jobs.json').read_text());selected=[];players=Counter();families=Counter();seen=set();ledger=[]
    config_path=source/'config.json'
    config=json.loads(config_path.read_text()) if config_path.exists() else {}
    if config.get('prefer_multiround',False):
        jobs=sorted(jobs,key=lambda job:(len(job['raw']['game']['round_robin'])<=job['raw']['game']['n_players'],job['index']))
    for job in jobs:
        path=source/f"cases/{job['index']}/result.json"
        if not path.exists():continue
        result=json.loads(path.read_text());status=result['status']
        if status=='verified' and result.get('selection_version')!='ego-k-coverage-v2':
            status='awaiting_selection_refresh'
        if status=='verified':
            canonical=canonical_parent(job['raw'])
            if canonical in seen:status='isomorphic_duplicate_parent'
            elif players[result['players']]>=50:status='player_quota'
            elif families[result['family']]>=8:status='family_cap'
            else:
                selected.append((job,result));seen.add(canonical);players[result['players']]+=1;families[result['family']]+=1;status='selected'
        ledger.append(dict(index=job['index'],parent_id=job['parent_id'],status=status,solver_status=result['status'],reason=result.get('reason')))
    return selected,ledger,players


def package(source,out):
    selected,ledger,players=selection(source)
    if len(selected)!=100:raise ValueError(f'Need 100 parents; have {len(selected)} ({dict(players)})')
    config=json.loads((source/'config.json').read_text())
    multi=sum(r['total_proposals']>r['players'] for _,r in selected)
    if multi<config.get('min_multiround_parents',0):
        raise ValueError(f'Insufficient multi-round coverage: {multi}')
    out.mkdir(parents=True,exist_ok=False);(out/'references').mkdir();(out/'audits').mkdir()
    from training.strategic_slices.freeze import source_identity
    source_hashes=source_identity()
    for name in source_hashes:
        destination=out/'source'/name;destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(name,destination)
    for path in Path('examples/strategic_slices').glob('*.py'):
        destination=out/'source'/path;destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(path,destination);source_hashes[str(path)]=file_hash(path)
    (out/'provenance').mkdir()
    for name in ('jobs.json','config.json'):
        shutil.copyfile(source/name,out/'provenance'/name)
    parents=[];references=[];rows=[]
    for job,result in selected:
        pid=job['parent_id'];rid=digest((pid,result['certificate']['policy_sha256']))[:24]
        folder=source/f"cases/{job['index']}";file=f'references/{rid}.npz'
        shutil.copyfile(folder/'reference.npz',out/file)
        assert file_hash(out/file)==result['reference_sha256']
        parent=dict(id=pid,canonical_identity=canonical_parent(job['raw']),raw=job['raw'],players=result['players'],family=result['family'],origin=job['origin'],
            calibration_family=job.get('calibration_family',False),source_index=job['index'],source_result_sha256=file_hash(folder/'result.json'),
            total_proposals=result['total_proposals'],worlds=result['worlds'],native_nodes=result['nodes'],entrance_selection=result['selection'])
        parents.append(parent)
        references.append(dict(id=rid,parent_id=pid,history=[],certificate=result['certificate'],file=file,sha256=file_hash(out/file),
            belief_regime='initial-prior-plus-reference-reach',oracle_contract=CONTRACT,
            native_audit=result['native_audit'],initial_native_terminal_profile=True))
        for row in result['candidates']:
            row=deepcopy(row);row.update(reference_id=rid,family=parent['family'],oracle_contract=CONTRACT)
            rows.append(row)
    families=defaultdict(list)
    for parent in parents:families[parent['family']].append(parent['id'])
    calibration={p['family'] for p in parents if p['calibration_family']}
    mapping={f:'train' for f in calibration};counts=Counter(train=sum(len(families[f]) for f in calibration))
    targets=dict(train=63,validation=12,test=25)
    for family in sorted(families,key=lambda f:(-len(families[f]),digest((20261004,f)))):
        if family in mapping:continue
        split=max(targets,key=lambda s:targets[s]-counts[s]);mapping[family]=split;counts[split]+=len(families[family])
    for row in parents+rows:
        row['split']=mapping[row['family']];row['calibration_family']=row['family'] in calibration
    write_rows(out/'parents.jsonl',parents);write_rows(out/'references.jsonl',references);write_rows(out/'candidates.jsonl',rows)
    write_rows(out/'generation_ledger.jsonl',ledger)
    manifest=dict(version=VERSION,oracle_contract=CONTRACT,status='awaiting-independent-audit',training_compatible=False,D_measured=False,
        target=dict(parents=100,final_slices_after_D=100,multiple_candidates_per_parent=True),
        coverage=dict(multiround_parents=multi,min_multiround_parents=config.get('min_multiround_parents',0),
                      working_coverage_note=config.get('coverage_note'),
                      players_and_rounds=dict(Counter(f"{p['players']}p/{p['total_proposals']//p['players']}r" for p in parents)),
                      world_support_sizes=dict(Counter(p['worlds'] for p in parents)),
                      k=dict(Counter(r['k'] for r in rows)),
                      decision_kinds=dict(Counter(r['decision_kind'] for r in rows)),
                      information_positive_rows=sum(r['information_positive'] for r in rows),
                      information_positive_parents=len({r['parent_id'] for r in rows if r['information_positive']}),
                      detectable_information_rows=sum(r['detectable_information_value'] for r in rows),
                      information_channels={channel:dict(
                          measured_rows=sum(r['information_channels'].get(channel) is not None for r in rows),
                          maximum=max((r['information_channels'][channel] for r in rows
                                       if r['information_channels'].get(channel) is not None),default=None))
                          for channel in ('query_answer','future_public_history','entry_and_future_public_history')}),
        parents=len(parents),families=len(families),references=len(references),candidates=len(rows),
        players=dict(players),selection=dict(min_C=.1,min_increment=.05,min_S=.05,max_per_parent=16,max_parents_per_family=8,
            entrance_limit=24,min_oracle_information_set_mass=1e-10,min_distinct_histories=2,
            entrance_strata=['ego','remaining_proposals','proposal/response','focal_next_proposal_offset'],
            cap_policy='Cover every eligible ego/k pair, then cycle ego/remaining/kind strata preferring distinct entrances; preserve four existing collective calibration windows'),
        sampling='Enumerate positive reference-reach information sets in last 1/2/3 native proposal turns; stratified cap. No epsilon exploration or entrance re-solving.',
        oracle_scope='One certified initial-state terminal profile per parent, including full private world support. Own-utility epsilon-Nash and local support/response tie checks; not unique or formal sequential equilibrium.',
        continuation='Same saved profile for all partners and focal after k actual decisions. No re-solving.',
        information_contract='Named query/future-history/entry-plus-future-history channels. Same joint belief and physical tree in full/masked values. Null is unmeasured; channels are not additive.',
        k_contract='Focal proposal and response decisions count; k is a maximum. C/S compare complete contingent policies and are not sums of per-step scores.',
        splits={s:dict(parents=sum(p['split']==s for p in parents),candidates=sum(r['split']==s for r in rows)) for s in targets},
        source_jobs_sha256=file_hash(source/'jobs.json'),source_config_sha256=file_hash(source/'config.json'),
        packaging_and_audit_source_identity=source_hashes,
        files={str(f.relative_to(out)):file_hash(f) for f in out.rglob('*') if f.is_file()})
    write_json(out/'manifest.json',manifest)
    return manifest


def audit_parent(out,pid):
    dataset=TerminalCandidates(out);parent=dataset.parents[pid]
    rows=[r for r in dataset.candidates if r['parent_id']==pid]
    assert len({r['reference_id'] for r in rows})==1
    tree=dataset.reference(rows[0])
    report=audit_rows(tree,rows,pid)
    write_json(out/f'audits/{pid}.json',report)
    return report


def audit_rows(tree,rows,pid):
    tree.deadline=time.monotonic()+240
    before=tree.reference_identity()[0];certification=certify_policy(tree)
    if certification is None:raise ValueError('Full saved reference failed independent certification')
    assert before==tree.reference_identity()[0]
    values=tree.evaluate();checked=0;s_checks=0;max_gap=0.
    for number,row in enumerate(rows):
        masses=[]
        for member in row['members']:
            if member['history_encoding']=='native-action-indices':history=member['history']
            else:
                index=0;history=[]
                for action in member['history']:
                    ai=next(i for i,a in enumerate(tree.entries[index].actions) if stable(a.to_dict())==stable(action))
                    history.append(ai);index=tree.entries[index].children[ai]
            index,mass=prefix_joint_mass(tree,history,row['ego'],member['world_weights'])
            assert index==member['root_index'];assert tree.entries[index].actor==row['ego']
            assert len(tree.rules.spec.round_robin)-tree.entries[index].node.state.turn_index==member['remaining_proposals']
            assert 1<=member['remaining_proposals']<=3
            metric=window_values(tree,row['ego'],index,member['world_weights'],row['k'])
            for key in ('V_star','V_min','C_span'):assert abs(metric[key]-member[key])<1e-7
            base=float(np.array(member['world_weights'])@values[index][:,row['ego']])
            max_gap=max(max_gap,metric['V_star']-base)
            masses.append(mass);checked+=1
        total=sum(m.sum() for m in masses)
        assert abs(total-row['group_reach_probability'])<1e-9
        for mass,member in zip(masses,row['members']):
            assert np.allclose(mass/total,member['joint_world_masses'],atol=1e-9,rtol=0)
        # All positive information records, every collective control, and first
        # singleton per parent receive an independent S remeasurement.
        if number==0 or row['detectable_information_value'] or row['entry_kind']=='oracle-reach-collective':
            entries=[dict(root_index=m['root_index'],world_masses=m['joint_world_masses']) for m in row['members']]
            channel='entry_and_future_public_history' if row['entry_kind']=='oracle-reach-collective' else 'future_public_history'
            result=public_history_value(tree,ego=row['ego'],entries=entries,k=row['k'],seconds=15)
            assert abs(result['S']-row['information_channels'][channel])<1e-7
            for detail in row.get('query_details',[]):
                m=row['members'][0]
                query=masked_answer_value(tree,ego=row['ego'],root_index=m['root_index'],root_weights=m['world_weights'],query_slot=tuple(detail['slot']),k=row['k'])
                assert abs(query['S']-detail['S'])<1e-7
            s_checks+=1
    if max_gap>1e-6:
        raise ValueError(f'On-path oracle continuation is not locally optimal: {max_gap}')
    assert len(rows)>=2
    histories={stable(m['history']) for row in rows for m in row['members']};assert len(histories)>=2
    report=dict(parent_id=pid,reference_sha256=before,candidates=len(rows),members=checked,S_records_remeasured=s_checks,
        independent_equilibrium_certified=True,all_prefix_posteriors_verified=True,native_terminal_only=True,
        distinct_member_histories=len(histories),max_reference_window_gain=max_gap)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,default=Path('new/local_data/strategic_slices_oracle_consistent_search_v1'))
    p.add_argument('--output',type=Path);p.add_argument('--status',action='store_true');p.add_argument('--audit-parent')
    a=p.parse_args()
    if a.status:
        selected,ledger,players=selection(a.source)
        print(dict(selected=len(selected),players=dict(players),statuses=dict(Counter(r['solver_status'] for r in ledger)),
                   multiround=sum(r['total_proposals']>3 for _,r in selected)));return
    if a.audit_parent:audit_parent(a.output,a.audit_parent);return
    if not a.output.exists():package(a.source,a.output)
    dataset=TerminalCandidates(a.output)
    assert len({canonical_parent(p['raw']) for p in dataset.parents.values()})==100
    def launch(pid):
        with (a.output/f'audits/{pid}.log').open('w') as log:
            subprocess.run([sys.executable,'-m','examples.strategic_slices.package_oracle_consistent','--output',str(a.output),'--audit-parent',pid],
                stdout=log,stderr=subprocess.STDOUT,check=True,timeout=300,
                env=dict(os.environ,OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1'))
        print('audited',pid,flush=True)
        return json.loads((a.output/f'audits/{pid}.json').read_text())
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(launch,dataset.parents))
    write_json(a.output/'audit.json',dict(parents=len(results),references_independently_recertified=len(results),
        candidates=sum(r['candidates'] for r in results),members_recomputed=sum(r['members'] for r in results),
        S_records_remeasured=sum(r['S_records_remeasured'] for r in results),all_prefix_posteriors_verified=True,
        all_native_terminal=True,same_initial_reference_throughout=True,
        max_reference_window_gain=max(r['max_reference_window_gain'] for r in results)))
    manifest=json.loads((a.output/'manifest.json').read_text());manifest['status']='oracle-consistent-candidate-pool-verified'
    manifest['files'].update({str(f.relative_to(a.output)):file_hash(f) for f in (a.output/'audits').glob('*.json')})
    manifest['files']['audit.json']=file_hash(a.output/'audit.json');write_json(a.output/'manifest.json',manifest)
    write_json(a.output/'CANDIDATES_VERIFIED.json',dict(manifest_sha256=file_hash(a.output/'manifest.json'),D_measured=False,final_100_slices_selected=False))
    print(dict(parents=manifest['parents'],candidates=manifest['candidates'],status=manifest['status']),flush=True)

if __name__=='__main__':main()
