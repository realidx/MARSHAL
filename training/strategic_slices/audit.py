"""Model-independent corpus audit: all references/entrances and sampled C values."""
import argparse
from collections import Counter
from pathlib import Path

import numpy as np
from .common import Dataset, write_json
from .build import structural_family
from .values import window_values, masked_answer_value
from training.b_sft.social_private_teacher import observed_slots


def fixed_entrance(dataset, parent, reference, record):
    """Independently reconstruct public likelihood before conditioning ego facts."""
    node = reference.rules.initial()
    masses = np.asarray(parent['world_weights'], dtype=float).copy()
    np.testing.assert_allclose(masses, reference.world_weights, atol=1e-12)
    epsilon = dataset.manifest['config']['reach_epsilon']
    for ai in record['history']:
        actions = reference.rules.actions(node)
        if type(ai) is not int or not 0 <= ai < len(actions):
            raise AssertionError('Invalid native entrance action index')
        probs = reference.probabilities(node)
        if probs.shape != (len(actions), reference.w):
            raise AssertionError('Reference probability shape mismatch')
        np.testing.assert_allclose(probs.sum(axis=0), 1., atol=1e-12)
        masses *= (1 - epsilon) * probs[ai] + epsilon / len(actions)
        node = reference.rules._apply(node, actions[ai])
    ego = record['ego']
    if reference.rules.actor(node) != ego or record['root_index'] != 0:
        raise AssertionError('Sparse entrance replay mismatch')
    if observed_slots(node, ego) != tuple((p, g) for p, g, _ in record['private_results']):
        raise AssertionError('Entrance private facts differ from received query targets')
    mask = np.array([list(w[ego]) == record['own'] and
                     all(w[p][g] == v for p, g, v in record['private_results'])
                     for w in reference.worlds])
    masses *= mask
    if masses.sum() <= 0:
        raise AssertionError('Impossible entrance information set')
    masses /= masses.sum()
    np.testing.assert_allclose(masses, record['entry_world_weights'], atol=1e-10)
    return node, masses


def audit(dataset):
    result = dict(dataset_sha256=dataset.sha, model_independent=True, splits={})
    for split, parents in dataset.parents.items():
        slices = dataset.slices[split]
        checked = 0; sampled_values = 0; sampled_information = 0; strata = set()
        backends = Counter()
        for parent in parents:
            if structural_family(parent['raw']['game']) != parent['family']:
                raise AssertionError('Structural identity mismatch')
            participants = {a['player_id'] for g in parent['raw']['game']['goals'] for a in g['required_actions']}
            if len(participants) != parent['players']:
                raise AssertionError('Isolated player')
            fixed = parent.get('reference_backend') == 'fixed-myopic-v1'
            bounded = parent.get('reference_backend') == 'bounded-next-own-v1'
            tree = None if bounded else dataset.reference(parent)
            backends[parent.get('reference_backend', 'synchronous-certified-v1')] += 1
            for s in (s for s in slices if s['parent_id'] == parent['id']):
                if bounded:
                    from .common import replay_node
                    tree = dataset.reference(parent, s)
                    root = replay_node(tree.rules, s['history'])
                    if root.state.public_state() != tree.entries[0].node.state.public_state():
                        raise AssertionError('Bounded entrance replay mismatch')
                    if observed_slots(root, s['ego']) != tuple((p, g) for p, g, _ in s['private_results']):
                        raise AssertionError('Bounded private-answer record mismatch')
                    if tree.entries[0].actor != s['ego'] or s['absolute_cutoff'] != tree.cutoff:
                        raise AssertionError('Bounded actor/cutoff mismatch')
                    index = 0
                    masses = np.array(parent['world_weights'], dtype=float)
                    mask = np.array([list(w[s['ego']]) == s['own'] and
                        all(w[p][g] == v for p, g, v in s['private_results']) for w in tree.worlds])
                    masses *= mask
                    if masses.sum() <= 0:
                        raise AssertionError('Impossible bounded entrance')
                    masses /= masses.sum()
                    np.testing.assert_allclose(masses, s['entry_world_weights'], atol=1e-10)
                elif fixed:
                    root, masses = fixed_entrance(dataset, parent, tree, s)
                    index = 0
                else:
                    index = 0; masses = tree.world_weights.copy()
                    for ai in s['history']:
                        epsilon = dataset.manifest['config']['reach_epsilon']
                        masses *= (1 - epsilon) * tree.policy[index][ai] + epsilon / len(tree.entries[index].actions)
                        index = tree.entries[index].children[ai]
                    if index != s['root_index'] or tree.entries[index].actor != s['ego']:
                        raise AssertionError('Entrance replay mismatch')
                    mask = np.array([list(w[s['ego']]) == s['own'] and all(w[p][g] == v for p, g, v in s['private_results']) for w in tree.worlds])
                    masses *= mask; masses /= masses.sum()
                    np.testing.assert_allclose(masses, s['entry_world_weights'], atol=1e-10)
                if s['C_span'] <= dataset.manifest['config']['min_c']:
                    raise AssertionError('Nonconsequential retained window')
                checked += 1
                stratum = (parent['players'], len(parent['raw']['game']['round_robin']) // parent['players']) if fixed else parent['players']
                if bounded:
                    stratum = (parent['players'], tree.lookahead_rr, s['information_positive'])
                if stratum not in strata:
                    if fixed:
                        from .sparse import SparseWindow
                        value_tree = SparseWindow(tree, root, s['ego'], masses, s['k'],
                                                  max_nodes=dataset.manifest['config']['max_nodes'], seconds=120)
                    else:
                        value_tree = tree
                    value = window_values(value_tree, s['ego'], index, masses, s['k'])
                    np.testing.assert_allclose([value['V_star'], value['C_span']], [s['V_star'], s['C_span']], atol=1e-9)
                    if fixed or bounded:
                        for info in s['information_values']:
                            slot = tuple(info['slot'])
                            measured = masked_answer_value(value_tree, ego=s['ego'], root_index=0,
                                                           root_weights=masses, query_slot=slot, k=s['k'])
                            ai = next(i for i, a in enumerate(value_tree.entries[0].actions)
                                      if a.to_dict().get('action') == 'INVESTIGATE' and
                                      (a.to_dict()['player'], a.to_dict()['goal']) == slot)
                            conditional = max(0., measured['full']['root_action_values'][ai] -
                                              measured['masked']['root_action_values'][ai])
                            np.testing.assert_allclose([measured['S'], conditional],
                                                       [info['S'], info['S_given_query']], atol=1e-9)
                            sampled_information += 1
                    strata.add(stratum); sampled_values += 1
        result['splits'][split] = dict(parents=len(parents), slices=len(slices),
            players=dict(Counter(p['players'] for p in parents)), families=len({p['family'] for p in parents}),
            windows_by_k=dict(Counter(s['k'] for s in slices)),
            private_information_positive=sum(s['information_positive'] for s in slices),
            delayed_consequence_windows=sum(s['length_curve'][0]['C_span'] <= .1 and s['k'] > 1 for s in slices),
            checked_reference_policies=len(parents), checked_entrance_posteriors=checked,
            independently_recomputed_value_samples=sampled_values,
            independently_recomputed_information_samples=sampled_information,
            reference_backends=dict(backends),
            per_parent_slice_range=[min(p['slices'] for p in parents), max(p['slices'] for p in parents)])
    return result


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--data', type=Path, required=True)
    cli.add_argument('--output', type=Path, required=True)
    args = cli.parse_args()
    result = audit(Dataset(args.data, ('train', 'validation', 'test')))
    write_json(args.output, result)
    print(result)


if __name__ == '__main__':
    main()
