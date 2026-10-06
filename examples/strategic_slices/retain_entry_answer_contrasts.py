"""Make an eight-per-parent revision retaining strong native answer contrasts.

The old frozen questions and model results stay intact. New questions are
ordinary fixed-information singleton slices. A separate relation stores the
collective S and reach weights; it is never copied into a singleton's S fields.
"""
import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import json
from pathlib import Path
import shutil

import numpy as np

from new.benac_slice_pilot.metrics import optimal_value
from training.strategic_slices.common import file_hash, stable, write_json, write_rows
from training.strategic_slices.oracle_consistent import decision_capacity, prefix_joint_mass
from training.strategic_slices.terminal_candidates import TerminalCandidates
from training.strategic_slices.values import window_values
from examples.strategic_slices.rebalance_candidates import select_parent, distribution


def singleton(group, member, template, tree):
    root = group['root_index']; ego = group['ego']
    future = tree.rules.spec.round_robin[tree.entries[root].node.state.turn_index:]
    offsets = [i for i, p in enumerate(future) if p == ego]
    metric = window_values(tree, ego, root, member['world_weights'], 1)
    assert all(abs(metric[key]-member[key]) < 1e-8 for key in ('C_span', 'V_star', 'V_min'))
    assert np.allclose(metric['root_Q'], member['root_Q'], atol=1e-8, rtol=0)
    _, mass = prefix_joint_mass(tree, member['history'], ego, member['world_weights'])
    assert abs(mass.sum()-member['oracle_information_set_mass']) < 1e-9
    ref_value = float(np.asarray(member['world_weights']) @ tree.evaluate()[root][:, ego])
    # A future private answer/public observation cannot affect this one action.
    # Entry-answer information belongs to the relation, not these fields.
    m = dict(root_index=root, history=member['history'], history_encoding='native-action-indices',
        probability=1., world_weights=member['world_weights'], joint_world_masses=member['world_weights'],
        remaining_proposals=member['remaining_proposals'], **metric)
    return dict(id=member['candidate_id'], entrance_id=member['entrance_id'],
        parent_id=group['parent_id'], reference_id=template['reference_id'],
        family=template['family'], split=template['split'],
        calibration_family=template.get('calibration_family', False),
        oracle_contract=template['oracle_contract'], ego=ego, k=1,
        **{key: metric[key] for key in ('C_span', 'V_star', 'V_min')}, members=[m],
        entry_kind='oracle-reach-singleton', information_scope='one-entrance-conditioned-on-own-information',
        information_channels=dict(query_answer=0., future_public_history=0., entry_and_future_public_history=None),
        group_reach_probability=member['oracle_information_set_mass'],
        decision_kind=group['decision_kind'], focal_next_proposal_offset=offsets[0] if offsets else None,
        focal_remaining_proposals=len(offsets),
        decision_capacity=decision_capacity(tree, root, ego, member['world_weights']),
        k_is_maximum_controlled_decisions=True, reference_value=ref_value,
        reference_window_gain=metric['V_star']-ref_value,
        information_positive=False, detectable_information_value=False)


def package(source, audit, out):
    if out.exists():
        raise ValueError('Use a new output directory')
    data = TerminalCandidates(source)
    marker = json.loads((source/'CANDIDATES_VERIFIED.json').read_text())
    assert marker['manifest_sha256'] == file_hash(source/'manifest.json')
    summary = json.loads((audit/'summary.json').read_text())
    assert summary['complete'] and summary['source_manifest_sha256'] == marker['manifest_sha256']
    assert summary['implementation_sha256'] == file_hash(Path('training/strategic_slices/entry_answers.py'))
    assert summary['audit_script_sha256'] == file_hash(Path('examples/strategic_slices/audit_entry_answers.py'))
    original = {r['id']: r for r in data.candidates}
    by_parent = defaultdict(list)
    for row in data.candidates:
        by_parent[row['parent_id']].append(row)
    selected = []; relations = []; ledger = []; totals = defaultdict(Counter)
    for pid in sorted(data.parents):
        existing = by_parent[pid]
        record = json.loads((audit/(pid+'.json')).read_text())
        assert record['policy_sha256'] == data.references[existing[0]['reference_id']]['certificate']['policy_sha256']
        eligible = [g for g in record['groups'] if g['S'] > .05 and g['must_change_pairs']
                    and all(m['C_span'] > .1 and m['oracle_information_set_mass'] > 1e-10 for m in g['members'])]
        # Prefer contrasts contributing more value under the *original* reach,
        # then conditional S. Never rebalance the answer probabilities.
        eligible.sort(key=lambda g: (-g['group_reach_probability']*g['S'], -g['S'], g['id']))
        kept = None; chosen = None
        for group in eligible:
            tree = data.reference(existing[0])
            added = [singleton(group, m, existing[0], tree) for m in group['members']
                     if m['candidate_id'] not in original]
            required = [m['candidate_id'] for m in group['members']]
            trial_totals = deepcopy(totals)
            try:
                kept, diagnostic = select_parent(existing+added, data.parents[pid]['players'], trial_totals,
                    required_ids=required, existing_ids=set(original))
            except ValueError:
                continue
            # Independent masked dynamic program checks the closed-form S.
            reach_mass = sum(m['oracle_information_set_mass'] for m in group['members'])
            assert abs(reach_mass-group['group_reach_probability']) < 1e-9
            assert all(abs(m['probability']-m['oracle_information_set_mass']/reach_mass) < 1e-9
                       for m in group['members'])
            masses = np.sum([m['joint_world_masses'] for m in group['members']], axis=0)
            masked = optimal_value(tree, ego=group['ego'], root_index=group['root_index'],
                root_weights=masses, k=1, masked_slot=tuple(group['query_slot']))
            assert abs(masked['value']-group['V_masked']) < 1e-8
            for m in group['members']:
                full = optimal_value(tree, ego=group['ego'], root_index=group['root_index'],
                    root_weights=m['world_weights'], k=1)
                assert abs(full['value']-m['V_star']) < 1e-8
            chosen = dict(group, candidate_ids=required, independent_DP_verified=True,
                          reference_id=existing[0]['reference_id'])
            relations.append(chosen); totals = trial_totals
            break
        if kept is None:
            kept, diagnostic = select_parent(existing, data.parents[pid]['players'], totals)
        selected.extend(kept)
        ledger.append(dict(parent_id=pid, eligible_contrasts=len(eligible),
            retained_contrast_id=None if chosen is None else chosen['id'], **diagnostic))
        print(pid, 'contrast', None if chosen is None else chosen['S'], flush=True)
    assert len(selected) == 800 and set(Counter(r['parent_id'] for r in selected).values()) == {8}
    assert len({r['id'] for r in selected}) == 800
    ids = {r['id'] for r in selected}
    assert all(set(g['candidate_ids']) <= ids for g in relations)
    unchanged = sorted(ids & original.keys()); added_ids = sorted(ids-original.keys())
    assert all(stable(r) == stable(original[r['id']]) for r in selected if r['id'] in original)
    shutil.copytree(source, out)
    proof = out/'provenance'/'before_entry_answer_revision'
    proof.mkdir()
    for name in ('manifest.json', 'CANDIDATES_VERIFIED.json', 'audit.json', 'balance.json', 'selection_ledger.jsonl', 'REPORT.md'):
        shutil.move(str(out/name), str(proof/name))
    write_rows(out/'candidates.jsonl', selected)
    write_rows(out/'entry_answer_relations.jsonl', relations)
    write_rows(out/'selection_ledger.jsonl', ledger)
    write_json(out/'D_reuse.json', dict(unchanged_candidate_ids=unchanged, requires_new_D=added_ids,
        removed_candidate_ids=sorted(original.keys()-ids),
        rule='Reuse results only for byte-identical candidate records and identical reference/config; group S never substitutes for model D.'))
    policy = dict(exact_per_parent=8, positive_threshold=.05, epsilon=.1,
        required='Keep every answer member of one strong must-change group per eligible parent; preserve existing player/k/kind categories and collective controls.',
        group_priority='Descending oracle-reach probability times S, then S, then stable ID.',
        subset_priority='Minimize changed questions, then original distribution-balancing objectives.',
        scope='One-decision entry-private-answer value; future-query S is unchanged. No group S is assigned to individual questions.')
    write_json(out/'balance.json', dict(policy=policy, before=distribution(data.candidates, data.parents),
                                     after=distribution(selected, data.parents)))
    sources = ('training/strategic_slices/entry_answers.py', 'training/strategic_slices/terminal_candidates.py',
               'training/strategic_slices/test_entry_answers.py', 'examples/strategic_slices/audit_entry_answers.py',
               'examples/strategic_slices/retain_entry_answer_contrasts.py', 'examples/strategic_slices/rebalance_candidates.py')
    for path in sources:
        dest = out/'source'/path; dest.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(path, dest)
    shutil.copytree(audit, out/'provenance'/'entry_answer_scan')
    audit_record = dict(mode='unchanged-reference-with-new-entrance-measurements',
        source_manifest_sha256=file_hash(source/'manifest.json'), parents=100, candidates=800,
        strong_entry_answer_groups=len(relations), group_splits=dict(Counter(g['split'] for g in relations)),
        singleton_questions_in_groups=sum(len(g['members']) for g in relations),
        unchanged_questions=len(unchanged), new_questions=len(added_ids),
        minimum_group_S=min((g['S'] for g in relations), default=None),
        maximum_group_S=max((g['S'] for g in relations), default=None),
        inherited_reference_certifications=100, selected_group_DP_and_new_member_C_verified=True,
        new_oracle_solves=0, new_model_calls=0, D_complete_for_revision=False)
    write_json(out/'audit.json', audit_record)
    manifest = deepcopy(data.manifest)
    manifest.update(derivation=dict(source=str(source), source_manifest_sha256=file_hash(source/'manifest.json')),
                    subset_selection=policy, entry_answer_contrasts=audit_record)
    after = distribution(selected, data.parents)
    manifest['coverage'].update(k=after['k'], decision_kinds=after['decision_kinds'])
    for field in ('information_positive', 'detectable_information_value'):
        key = 'information_positive_rows' if field == 'information_positive' else 'detectable_information_rows'
        manifest['coverage'][key] = sum(r[field] for r in selected)
    manifest['coverage']['information_positive_parents'] = len({r['parent_id'] for r in selected if r['information_positive']})
    for channel in manifest['coverage']['information_channels']:
        values = [r['information_channels'][channel] for r in selected if r['information_channels'].get(channel) is not None]
        manifest['coverage']['information_channels'][channel] = dict(measured_rows=len(values), maximum=max(values, default=None))
    manifest['packaging_and_audit_source_identity'].update({path: file_hash(Path(path)) for path in sources})
    manifest['selection']['cap_policy'] = policy
    # Existing singleton channel coverage remains unchanged. The new channel is
    # explicitly collective, recorded separately instead of inventing row labels.
    manifest['coverage']['entry_private_answer_groups'] = len(relations)
    manifest['files'] = {str(p.relative_to(out)): file_hash(p) for p in out.rglob('*') if p.is_file()}
    write_json(out/'manifest.json', manifest)
    TerminalCandidates(out)
    assert all(file_hash(out/r['file']) == file_hash(source/r['file']) for r in data.references.values())
    assert file_hash(out/'parents.jsonl') == file_hash(source/'parents.jsonl')
    assert file_hash(out/'references.jsonl') == file_hash(source/'references.jsonl')
    write_json(out/'CANDIDATES_VERIFIED.json', dict(manifest_sha256=file_hash(out/'manifest.json'),
        audit_mode=audit_record['mode'], D_measured=False, final_100_slices_selected=False))
    print(json.dumps(audit_record, indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, default=Path('new/local_data/strategic_slices_oracle_consistent_candidates_v2'))
    p.add_argument('--audit', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args(); package(a.source, a.audit, a.output)
