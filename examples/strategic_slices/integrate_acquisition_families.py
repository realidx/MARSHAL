"""Replace six redundant training parents with audited acquisition families.

Preserve the frozen source and every retained question byte-for-byte. Keep 100
parents x 8 slices, existing contrast groups and player/round/split quotas.
New roots may precede terminal by four proposals, but k remains at most three.
"""
import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import shutil

import numpy as np

from examples.strategic_slices.rebalance_candidates import distribution
from training.strategic_slices.build import structural_family
from training.strategic_slices.common import digest, file_hash, stable, write_json, write_rows
from training.strategic_slices.oracle_consistent import canonical_parent, entrance_pool, prefix_joint_mass, decision_capacity
from training.strategic_slices.terminal_candidates import TerminalCandidates, restore_reference, LOCAL_DECISION_ENTRANCE_CONTRACT
from training.strategic_slices.values import window_values


def sources():
    base = Path('new/local_data')
    yield base/'strategic_slices_native_acquisition_search_v5', 'three_targeted_00015'
    yield base/'strategic_slices_native_acquisition_search_v6', 'historical_00000'
    folder = base/'strategic_slices_acquisition_families_v1'
    for row in json.loads((folder/'summary.json').read_text())['results']:
        if row.get('strong_witnesses', 0):
            yield folder, row['name']


def finalize_sources(out):
    """Freeze the actual new implementation instead of inheriting v3 code claims."""
    paths=[Path('examples/strategic_slices/integrate_acquisition_families.py'),Path('examples/strategic_slices/expand_acquisition_families.py'),
        Path('examples/strategic_slices/verify_native_acquisition.py'),
        Path('training/strategic_slices/oracle_consistent.py'),Path('training/strategic_slices/terminal_candidates.py'),
        Path('training/strategic_slices/terminal_d.py'),Path('examples/strategic_slices/run_terminal_d.py')]
    manifest=json.loads((out/'manifest.json').read_text())
    for key in ('source_jobs_sha256','source_config_sha256','entry_answer_contrasts'):
        if key in manifest:manifest['derivation']['inherited_'+key]=manifest.pop(key)
    manifest['entry_answer_contrasts']=dict(retained_groups=10,source='Unchanged v3 relation records; original audit in derivation.')
    for path in paths:
        destination=out/'source'/path;destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(path,destination)
    manifest['packaging_and_audit_source_identity']={str(p):file_hash(p) for p in paths}
    manifest['files']={str(p.relative_to(out)):file_hash(p) for p in out.rglob('*') if p.is_file()
        and p not in (out/'manifest.json',out/'CANDIDATES_VERIFIED.json')}
    write_json(out/'manifest.json',manifest)
    TerminalCandidates(out)
    marker=json.loads((out/'CANDIDATES_VERIFIED.json').read_text())
    marker['manifest_sha256']=file_hash(out/'manifest.json');write_json(out/'CANDIDATES_VERIFIED.json',marker)


def question(tree, entrance, metric, pid, rid, family, s=0., slot=None):
    root, ego = entrance['root_index'], entrance['ego']
    weights = entrance['entry_world_weights']
    eid = digest((pid,root,ego,entrance['own'],entrance['private_results']))[:24]
    member = dict(root_index=root, history=entrance['history'], history_encoding='native-action-indices',
        probability=1., world_weights=weights, joint_world_masses=weights,
        remaining_proposals=entrance['remaining_proposals'],
        **{key:metric[key] for key in ('V_star','V_min','C_span','root_Q')})
    return dict(id=digest((eid,metric['k']))[:24], entrance_id=eid, parent_id=pid, reference_id=rid,
        family=family, split='train', calibration_family=True, ego=ego, k=metric['k'],
        V_star=metric['V_star'], V_min=metric['V_min'], C_span=metric['C_span'], members=[member],
        entrance_contract=LOCAL_DECISION_ENTRANCE_CONTRACT, oracle_contract='initial-terminal-oracle-consistent-v1',
        entry_kind='oracle-reach-singleton', information_scope='one-entrance-conditioned-on-own-information',
        information_channels=dict(query_answer=s, future_public_history=None, entry_and_future_public_history=None),
        query_details=[] if slot is None else [dict(slot=slot,S=s)],
        information_measurement_scope='New query answer only; unmeasured public-history channels remain null. k=1 cannot use a future answer within its controlled window.',
        information_positive=s>.05, detectable_information_value=s>1e-6,
        group_reach_probability=entrance['oracle_information_set_mass'], decision_kind=entrance['decision_kind'],
        focal_next_proposal_offset=entrance['focal_next_proposal_offset'], focal_remaining_proposals=entrance['focal_remaining_proposals'],
        decision_capacity=decision_capacity(tree,root,ego,weights), k_is_maximum_controlled_decisions=True,
        reference_value=metric['V_star'], reference_window_gain=0.)


def new_parent(folder, name, out):
    raw = json.loads((folder/f'{name}_raw.json').read_text())
    result = json.loads((folder/f'{name}_result.json').read_text())
    proof_path = folder/f'{name}_independent_check.json'
    proof = json.loads(proof_path.read_text())
    assert proof['verified'] and proof['policy_sha256'] == result['certificate']['policy_sha256']
    for filename, sha in proof['source_files'].items():
        assert file_hash(folder/filename) == sha
    pid = digest({k:raw[k] for k in ('game','type_catalogues','background_prior')})[:24]
    family = structural_family(raw['game'])
    rid = digest((pid,result['certificate']['policy_sha256']))[:24]
    record = dict(id=rid,parent_id=pid,history=[],certificate=result['certificate'],file=f'references/{rid}.npz',
        belief_regime='initial-prior-plus-reference-reach', initial_native_terminal_profile=True,
        oracle_contract='initial-terminal-oracle-consistent-v1',native_audit=result['native_audit'])
    shutil.copyfile(folder/f'{name}_reference.npz',out/record['file'])
    record['sha256']=file_hash(out/record['file'])
    tree = restore_reference(raw,record,out/record['file'])
    pool = entrance_pool(tree,max_remaining_proposals=None)
    candidates = []
    for witness in result['masks']:
        if witness['S'] <= .05:continue
        entrance = next(e for e in pool if e['root_index']==witness['root_index'] and e['ego']==witness['ego']
                        and e['own']==witness['own'])
        for metric in witness['length_curve']:
            if metric['C_span']>.1:
                candidates.append(question(tree,entrance,metric,pid,rid,family,metric['S'],witness['slot']))
    # Core acquisition windows survive selection before any generic cap.
    selected = [r for r in candidates if r['information_positive']]
    assert len(selected)>=2 and len(selected)<8
    existing = {r['id'] for r in candidates}
    # Broadly reachable single-decision alternatives, with same-profile beliefs.
    for entrance in sorted(pool,key=lambda e:(-e['oracle_information_set_mass'],e['ego'],e['root_index'],e['own'])):
        metric=dict(k=1,**window_values(tree,entrance['ego'],entrance['root_index'],entrance['entry_world_weights'],1))
        if metric['C_span']<=.1:continue
        row = question(tree,entrance,metric,pid,rid,family)
        if row['id'] not in existing:candidates.append(row);existing.add(row['id'])
        if len(candidates)>=32 and {r['ego'] for r in candidates}==set(range(tree.n)):break
    while len(selected)<8:
        used={r['id'] for r in selected};egos={r['ego'] for r in selected}
        kinds={r['decision_kind'] for r in selected};entrances={r['entrance_id'] for r in selected}
        available=[r for r in candidates if r['id'] not in used]
        if not available:raise ValueError('Fewer than eight eligible representative slices')
        available.sort(key=lambda r:(r['ego'] in egos,r['decision_kind'] in kinds,
            r['entrance_id'] in entrances,-r['group_reach_probability'],r['id']))
        selected.append(available[0])
    for row in selected:
        m=row['members'][0]
        index,masses=prefix_joint_mass(tree,m['history'],row['ego'],m['world_weights'])
        assert index==m['root_index'] and abs(float(masses.sum())-row['group_reach_probability'])<1e-9
        metric=window_values(tree,row['ego'],index,m['world_weights'],row['k'])
        for key in ('V_star','V_min','C_span','root_Q'):
            np.testing.assert_allclose(metric[key],m[key],atol=1e-8,rtol=0)
    parent=dict(id=pid,family=family,split='train',calibration_family=True,raw=raw,
        players=tree.n,total_proposals=len(tree.rules.spec.round_robin),worlds=tree.w,native_nodes=len(tree.entries),
        canonical_identity=canonical_parent(raw), origin=dict(kind='verified-native-acquisition-family',source=str(folder),name=name),
        entrance_selection=dict(core_acquisition_windows_protected=True,remaining_proposals_hard_cap=None,
            controlled_k_max=3,retained=8,filler='High oracle reach, then uncovered actor/action kind/public entrance; k=1 C>.1'),
        source_result_sha256=file_hash(folder/f'{name}_result.json'))
    write_json(out/'provenance'/f'{pid}_independent_check.json',proof)
    print(name,'prepared',len(selected),'strong',sum(r['information_positive'] for r in selected),flush=True)
    return parent,record,selected


def package(source,out):
    if out.exists():raise ValueError('Use a new output directory')
    data=TerminalCandidates(source)
    assert json.loads((source/'CANDIDATES_VERIFIED.json').read_text())['manifest_sha256']==file_hash(source/'manifest.json')
    out.mkdir();(out/'references').mkdir();(out/'provenance').mkdir()
    added=[new_parent(folder,name,out) for folder,name in sources()]
    assert 5<=len({p['family'] for p,_,_ in added})<=10
    assert len({p['canonical_identity'] for p,_,_ in added})==len(added)
    assert not ({p['family'] for p,_,_ in added}&{p['family'] for p in data.parents.values()})
    protected={g['parent_id'] for g in data.entry_answer_relations}
    protected.update(r['parent_id'] for r in data.candidates if r['information_positive'] or r['entry_kind']!='oracle-reach-singleton')
    removed=set();family_counts=Counter(p['family'] for p in data.parents.values());replacements=[]
    for parent,_,_ in added:
        eligible=[p for p in data.parents.values() if p['id'] not in protected|removed and p['split']=='train'
            and not p.get('calibration_family') and p['players']==parent['players'] and p['total_proposals']==parent['total_proposals']]
        if not eligible:raise ValueError('No replacement preserving protected rows and player/round quotas')
        old=min(eligible,key=lambda p:(-family_counts[p['family']],p['family'],p['id']))
        removed.add(old['id']);family_counts[old['family']]-=1
        replacements.append(dict(old_parent_id=old['id'],new_parent_id=parent['id'],reason='Unprotected training parent in most redundant eligible family; same player count and proposal count.'))
    parents=[p for p in data.parents.values() if p['id'] not in removed]+[p for p,_,_ in added]
    refs=[r for r in data.references.values() if r['parent_id'] not in removed]+[r for _,r,_ in added]
    rows=[r for r in data.candidates if r['parent_id'] not in removed]+[r for _,_,rs in added for r in rs]
    for ref in refs:
        dest=out/ref['file']
        if not dest.exists():shutil.copyfile(source/ref['file'],dest)
    assert len(parents)==100 and len(rows)==800 and set(Counter(r['parent_id'] for r in rows).values())=={8}
    assert Counter((p['players'],p['total_proposals'],p['split']) for p in parents)==Counter((p['players'],p['total_proposals'],p['split']) for p in data.parents.values())
    for filename,records in [('parents',parents),('references',refs),('candidates',rows),('entry_answer_relations',data.entry_answer_relations)]:
        write_rows(out/(filename+'.jsonl'),records)
    original={r['id']:r for r in data.candidates};unchanged=[r['id'] for r in rows if r['id'] in original]
    assert all(stable(r)==stable(original[r['id']]) for r in rows if r['id'] in original)
    # Actual D was measured on v2, not on the intervening v3 revision.
    v2=TerminalCandidates(Path('new/local_data/strategic_slices_oracle_consistent_candidates_v2'))
    measured={r['id']:r for r in v2.candidates};reusable=[]
    for row in rows:
        if row['id'] not in measured:continue
        assert stable(row)==stable(measured[row['id']])
        ref=next(r for r in refs if r['id']==row['reference_id'])
        assert stable(ref)==stable(v2.references[row['reference_id']])
        assert file_hash(out/ref['file'])==file_hash(v2.root/ref['file'])
        reusable.append(row['id'])
    pending=sorted({r['id'] for r in rows}-set(reusable))
    write_json(out/'D_reuse.json',dict(source_v2_manifest_sha256=file_hash(v2.root/'manifest.json'),
        reuse_eligible_candidate_ids=sorted(reusable),requires_new_D=pending,new_model_calls=0,
        rule='Eligibility only: identical question/reference bytes. Reuse requires matching model/config and the same per-slice replica seeds. Do not resume a v2 job under this new manifest. No result files are rewritten here.'))
    write_json(out/'selection_ledger.json',replacements)
    balance=distribution(rows,{p['id']:p for p in parents});write_json(out/'balance.json',balance)
    audit=dict(parents=100,candidates=800,new_parents=len(added),new_candidates=8*len(added),
        unchanged_from_v3=len(unchanged),D_reuse_eligible=len(reusable),requires_new_D=len(pending),
        strong_acquisition_families=len(added),strong_acquisition_rows=sum(r['information_positive'] for _,_,rs in added for r in rs),
        retained_entry_answer_groups=len(data.entry_answer_relations),
        new_candidate_C_and_prefix_posteriors_verified=True,inherited_questions_and_references_byte_identical=True,
        player_round_split_quotas_preserved=True,new_model_calls=0)
    write_json(out/'audit.json',audit)
    manifest=deepcopy(data.manifest)
    manifest.update(entrance_contract=LOCAL_DECISION_ENTRANCE_CONTRACT,
        derivation=dict(source=str(source),source_manifest_sha256=file_hash(source/'manifest.json')),
        acquisition_revision=audit,parents=100,candidates=800,references=len(refs),families=len({p['family'] for p in parents}),
        sampling='Retained questions unchanged. New parents protect certified initial acquisition k=2/3, then select high-reach representative k=1 entrances; no proposal-distance hard cap on new certified parents.',
        report='audit.json',checkpoint='acquisition-family-revision-v4')
    manifest['selection'].update(entrance_limit=None,cap_policy='Keep eight per parent; protect acquisition k=2/3 and all existing entry-answer/collective controls.')
    manifest['coverage'].update(k=balance['k'],decision_kinds=balance['decision_kinds'],
        world_support_sizes=dict(Counter(p['worlds'] for p in parents)),
        information_positive_rows=sum(r['information_positive'] for r in rows),
        information_positive_parents=len({r['parent_id'] for r in rows if r['information_positive']}),
        detectable_information_rows=sum(r['detectable_information_value'] for r in rows))
    for channel in manifest['coverage']['information_channels']:
        values=[r['information_channels'][channel] for r in rows if r['information_channels'].get(channel) is not None]
        manifest['coverage']['information_channels'][channel]=dict(measured_rows=len(values),maximum=max(values,default=None))
    manifest['subset_selection']=dict(exact_per_parent=8,protected_existing_information=True,protected_new_acquisition=True)
    for filename in ('manifest.json','CANDIDATES_VERIFIED.json'):
        shutil.copyfile(source/filename,out/'provenance'/('source_'+filename))
    manifest['files']={str(p.relative_to(out)):file_hash(p) for p in out.rglob('*') if p.is_file()}
    write_json(out/'manifest.json',manifest)
    TerminalCandidates(out)
    write_json(out/'CANDIDATES_VERIFIED.json',dict(manifest_sha256=file_hash(out/'manifest.json'),
        audit_mode='unchanged-source-plus-independent-new-family-checks',D_measured=False,final_100_slices_selected=False))
    finalize_sources(out)
    print(json.dumps(audit),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,default=Path('new/local_data/strategic_slices_oracle_consistent_candidates_v3'))
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();package(args.source,args.output)
