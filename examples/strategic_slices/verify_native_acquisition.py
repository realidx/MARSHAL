"""Reopen saved native witnesses, re-certify, and independently check values."""
import argparse
from copy import copy
import json
from pathlib import Path
import time

import numpy as np

from training.b_sft.social_private_teacher import observed_slots
from training.strategic_slices.common import file_hash, write_json
from training.strategic_slices.early_investigation import terminal_response_values
from training.strategic_slices.equilibrium import certify_policy
from training.strategic_slices.oracle_consistent import oracle_reach
from training.strategic_slices.terminal_candidates import restore_reference
from training.strategic_slices.values import masked_answer_value


def verify(folder, name):
    raw_path = folder / f'{name}_raw.json'
    result_path = folder / f'{name}_result.json'
    ref_path = folder / f'{name}_reference.npz'
    raw = json.loads(raw_path.read_text())
    result = json.loads(result_path.read_text())
    tree = restore_reference(raw, dict(history=[], certificate=result['certificate']), ref_path)
    tree.deadline = time.monotonic() + 180
    original_identity = tree.reference_identity()[0]
    certified = certify_policy(tree)
    assert certified is not None
    tree.values = certified['values']
    assert tree.reference_identity()[0] == original_identity
    reach, histories = oracle_reach(tree)
    reports = []
    for witness in result['masks']:
        if witness['S'] <= .05:
            continue
        root, ego, slot = witness['root_index'], witness['ego'], tuple(witness['slot'])
        assert root == 0, 'This independent global-BR check is for initial witnesses'
        weights = np.array(witness['world_weights'])
        full = terminal_response_values(tree, ego)
        no_query = terminal_response_values(tree, ego, forbid_queries=True)
        view = copy(tree)
        view.information_groups = dict(tree.information_groups)
        for i, entry in enumerate(tree.entries):
            if entry.actor != ego:
                continue
            slots = [s for s in observed_slots(entry.node, ego) if s != slot]
            groups = {}
            for wi, world in enumerate(tree.worlds):
                key = (world[ego], tuple(world[p][g] for p, g in slots))
                groups.setdefault(key, []).append(wi)
            view.information_groups[i] = tuple(np.array(ids) for ids in groups.values())
        masked = terminal_response_values(view, ego)
        fv, mv = float(weights @ full[root]), float(weights @ masked[root])
        assert abs(fv-witness['V_full']) < 1e-9
        assert abs(mv-witness['V_mask']) < 1e-9
        reference_hash = tree.reference_identity()[0]
        assert reference_hash == original_identity
        decisions = []
        for i, masses in reach.items():
            entry = tree.entries[i]
            if entry.actor != ego or slot not in observed_slots(entry.node, ego):
                continue
            q = np.stack([full[c] for c in entry.children])
            cells = []
            for ids in tree.information_groups[i]:
                mass = float(masses[ids].sum())
                if mass <= 1e-10:
                    continue
                posterior = masses[ids]/mass
                values = q[:, ids] @ posterior
                cells.append(dict(answer=tree.worlds[int(ids[0])][slot[0]][slot[1]],
                    mass=mass, Q=values.tolist(), best_actions=np.flatnonzero(values >= values.max()-1e-9).tolist(),
                    reference_probabilities=tree.policy[i][:, ids[0]].tolist()))
            if len({tuple(c['best_actions']) for c in cells}) > 1:
                decisions.append(dict(root_index=i, history=histories[i],
                    actions=[a.to_dict() for a in entry.actions], cells=cells,
                    public_mass=float(masses.sum())))
        checked = masked_answer_value(tree, ego=ego, root_index=root,
            root_weights=weights, query_slot=slot, k=2*len(tree.rules.spec.round_robin))
        ai = next(i for i, a in enumerate(tree.entries[root].actions)
            if a.to_dict() == dict(action='INVESTIGATE', player=slot[0], goal=slot[1]))
        reports.append(dict(slot=list(slot), V_full=fv, V_mask=mv, S=fv-mv,
            V_no_queries=float(weights @ no_query[root]),
            S_given_same_query=checked['full']['root_action_values'][ai]-checked['masked']['root_action_values'][ai],
            reference_query_probability=float(weights @ tree.policy[root][ai]),
            entrance_mass=float(reach[root].sum()),
            remaining_proposals=len(tree.rules.spec.round_robin),
            fits_three_proposal_entrance=len(tree.rules.spec.round_robin)<=3,
            length_curve=witness['length_curve'], answer_dependent_decisions=decisions))
    report = dict(name=name, verified=True, solver_calls=0, source_files={p.name:file_hash(p) for p in (raw_path,result_path,ref_path)},
        script_sha256=file_hash(Path(__file__)), policy_sha256=original_identity,
        recertification=certified['certificate'], native_audit=tree.audit_native(), witnesses=reports)
    write_json(folder / f'{name}_independent_check.json', report)
    print(name, 'verified', [(r['S'], len(r['answer_dependent_decisions'])) for r in reports], flush=True)
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--folder', type=Path, required=True)
    p.add_argument('--name', required=True)
    args = p.parse_args()
    verify(args.folder, args.name)
