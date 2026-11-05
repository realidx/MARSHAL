"""Native two-round, three-player loading, branch, privacy and recovery checks."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from training.b_sft.social_private_teacher import PrivateInvestigationRules, PrivateWindow
from training.b_sft.preference_contract import profile
from .audit import audit
from .build import structural_family
from .common import Dataset, VERSION, digest, file_hash, replay_node, write_json, write_rows
from .evaluate import Evaluator
from .reference import FixedReference
from .runtime import Collector, Rollout
from .sparse import SparseWindow
from .test_pipeline import mock_generate
from .values import window_values, masked_answer_value


def freeze_two_round_fixture(folder):
    """Freeze three explicit disjoint native games without a generated corpus."""
    source = Path(__file__).resolve().parents[2] / 'examples/strategic_slices/test_games.json'
    records = [r for r in json.loads(source.read_text()) if r['raw']['game']['n_players'] == 3]
    config = dict(reference_policy='fixed-myopic-v1', reach_epsilon=.25, max_nodes=30000,
                  max_k=2, min_c=.1, min_s=.05)
    parents, slices = {}, {}
    for row in records:
        raw, split = deepcopy(row['raw']), row['split']
        raw['game']['round_robin'] *= 2
        rules = PrivateInvestigationRules(raw)
        rules.background_prior = raw['background_prior']
        reference = FixedReference(rules)
        parent = dict(id=digest(raw)[:24], raw=raw, players=3, split=split,
                      family=structural_family(raw['game']), reference_backend='fixed-myopic-v1',
                      world_weights=reference.world_weights.tolist(), certificate=reference.certificate)
        initial = rules.initial()
        ego, world = rules.actor(initial), reference.worlds[0]
        query = next(i for i, a in enumerate(rules.actions(initial))
                     if a.to_dict().get('action') == 'INVESTIGATE' and
                     len({w[a.player][a.goal] for w in reference.worlds}) > 1)
        roots = [[query, 0, 0]]
        # This initial entrance is consequential and also audits every query S.
        if split == 'validation':
            roots.insert(0, [])
        chosen = []
        for history in roots:
            node, masses = initial, reference.world_weights.copy()
            for ai in history:
                masses *= .75 * reference.probabilities(node)[ai] + .25 / len(rules.actions(node))
                node = rules._apply(node, rules.actions(node)[ai])
            realized = replay_node(rules, history, world)
            facts = list(map(list, realized.state.private_results[ego]))
            masses *= np.array([w[ego] == world[ego] and all(w[p][g] == v for p, g, v in facts)
                                for w in reference.worlds])
            masses /= masses.sum()
            tree = SparseWindow(reference, node, ego, masses, 2, max_nodes=30000, seconds=30)
            curves = [dict(k=k, **window_values(tree, ego, 0, masses, k)) for k in (1, 2)]
            value = curves[-1]
            information = []
            for ai, action in enumerate(tree.entries[0].actions):
                native = action.to_dict()
                if native.get('action') == 'INVESTIGATE':
                    slot = (native['player'], native['goal'])
                    measured = masked_answer_value(tree, ego=ego, root_index=0, root_weights=masses,
                                                   query_slot=slot, k=2)
                    information.append(dict(slot=list(slot), S=measured['S'], S_given_query=max(0.,
                        measured['full']['root_action_values'][ai] - measured['masked']['root_action_values'][ai])))
            chosen.append(dict(id=digest((parent['id'], history))[:24], parent_id=parent['id'], split=split,
                root_index=0, history=history, ego=ego, own=list(world[ego]), private_results=facts,
                entry_world_weights=masses.tolist(), k=2, V_star=value['V_star'], C_span=value['C_span'],
                C_span_normalized=value['C_span'] / len(rules.spec.goals), length_curve=curves,
                information_values=information, information_positive=any(s['S'] > .05 for s in information)))
        parent['slices'] = len(chosen)
        parents[split], slices[split] = [parent], chosen
    files = {}
    for split in parents:
        for kind, rows in [('parents', parents[split]), ('slices', slices[split])]:
            name = f'{split}_{kind}.jsonl'
            write_rows(folder / name, rows)
            files[name] = dict(sha256=file_hash(folder / name), rows=len(rows))
    write_json(folder / 'manifest.json', dict(version=VERSION, config=config, files=files))
    write_json(folder / 'COMPLETE.json', dict(manifest_sha256=file_hash(folder / 'manifest.json')))
    return Dataset(folder, ('train', 'validation', 'test'))


class FixedRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.dataset = freeze_two_round_fixture(Path(cls.temporary.name))

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_contract_identity_and_full_tree_is_not_requested(self):
        data = Dataset(self.dataset.root)
        parent = deepcopy(data.parents['train'][0])
        self.assertFalse(data.reference(parent).certificate['equilibrium'])
        with self.assertRaisesRegex(ValueError, 'full public game tree'):
            data.tree(parent)
        data.cache.clear()
        parent['certificate']['contract_sha256'] = 'changed'
        with self.assertRaisesRegex(ValueError, 'contract identity'):
            data.reference(parent)
        self.assertNotIn('test', data.parents)

    def test_all_posteriors_and_sampled_values_audit_without_full_tree(self):
        report = audit(self.dataset)
        self.assertEqual(sum(s['checked_entrance_posteriors'] for s in report['splits'].values()), 4)
        self.assertEqual(sum(s['independently_recomputed_value_samples'] for s in report['splits'].values()), 3)
        self.assertGreater(report['splits']['validation']['independently_recomputed_information_samples'], 0)
        for split in report['splits'].values():
            self.assertEqual(split['reference_backends'], {'fixed-myopic-v1': 1})

    def test_second_round_history_replay_delivers_private_answer(self):
        parent = self.dataset.parents['train'][0]
        record = self.dataset.slices['train'][0]
        job = Rollout(self.dataset, parent, 42, 0, record)
        self.assertIsNone(job.tree)
        self.assertEqual(job.node.state.turn_index, 3)
        self.assertEqual(job.history, record['history'])
        visible = json.loads(job.request(0)['messages'][1]['content'])
        self.assertEqual(len(visible['private_results']), 1)
        self.assertEqual(visible['private_results'][0]['player'], record['private_results'][0][0])
        same_information = next(i for i, w in enumerate(job.rules.worlds)
                                if i != 0 and list(w[record['ego']]) == record['own'] and
                                all(w[p][g] == v for p, g, v in record['private_results']))
        other = Rollout(self.dataset, parent, 42, same_information, record)
        self.assertEqual(job.request(0), other.request(0))
        bad_world = next(i for i, w in enumerate(job.rules.worlds)
                         if any(w[p][g] != v for p, g, v in record['private_results']))
        with self.assertRaisesRegex(ValueError, 'incompatible with slice entrance'):
            Rollout(self.dataset, parent, 42, bad_world, record)

    def test_every_model_native_branch_uses_live_transition_and_exact_reference_tail(self):
        parent, record = self.dataset.parents['train'][0], self.dataset.slices['train'][0]
        reference = self.dataset.reference(parent)
        root = replay_node(reference.rules, record['history'], reference.worlds[0])
        for ai, action in enumerate(reference.rules.actions(root)):
            job = Rollout(self.dataset, parent, 42, 0, record)
            expected = job.rules.step(root, action, realized_world=job.world)
            job.step(ai)
            self.assertEqual(job.node.state.public_state(), expected.state.public_state())
            self.assertEqual(job.node.pending, expected.pending)
            # With the focal window exhausted, independently execute this
            # same deterministic continuation to terminal and compare utility.
            job.controlled = record['k']
            while not expected.state.is_terminal:
                chosen = reference.action_index(expected, job.world)
                expected = job.rules.step(expected, job.rules.actions(expected)[chosen], realized_world=job.world)
            job.advance_reference()
            self.assertEqual(job.utility, list(job.rules.terminal_payoffs(expected, job.world)))
            self.assertEqual(job.status, 'terminal')

    def test_both_arms_collect_and_restore_over_two_round_games(self):
        for arm in ('slices', 'selfplay'):
            collector = Collector(self.dataset, mock_generate, arm, replicas=4)
            rows, _, games, metrics = collector.collect(0, arm, token_target=25)
            self.assertGreaterEqual(metrics['generated_tokens'], 25)
            self.assertTrue(all(game['status'] == 'terminal' for game in games))
            self.assertTrue(all(row['native_node_index'] is None for row in rows))
            self.assertTrue(all('native_history' in row for row in rows))
            restored = Collector(self.dataset, mock_generate, arm, replicas=4)
            restored.restore(collector.state)
            self.assertEqual(collector.collect(1, arm, 25), restored.collect(1, arm, 25))

    def test_full_game_team_and_each_focal_seat_reach_second_round(self):
        report = Evaluator(self.dataset, mock_generate, split='test', repeats=1).run()
        self.assertEqual(len(report['games']), 4)
        self.assertTrue(all(g['status'] == 'terminal' for g in report['games']))
        second_round = [c for c in report['calls']
                        if json.loads(c['request']['messages'][1]['content'])['public_state']['turn_index'] >= 3]
        self.assertTrue(second_round)

    def test_incomplete_group_never_receives_a_terminal_task_reward(self):
        def truncate_last(requests):
            out = mock_generate(requests)
            out[-1]['completion'] = dict(finish_reason='length', raw_message=dict(tool_calls=[]))
            return out
        for arm in ('slices', 'selfplay'):
            collector = Collector(self.dataset, truncate_last, arm, replicas=4)
            rows, _, games, _ = collector.collect(0, arm, token_target=1)
            self.assertTrue(any(g['terminal_utility'] is None for g in games))
            self.assertTrue(all(r['task_advantage'] == 0 for r in rows))
            self.assertTrue(any(r['protocol_advantage'] == -.2 for r in rows))

    def test_sparse_cross_k_values_and_query_masks_equal_complete_native_tree(self):
        required = [dict(player_id=0, action_id=0), dict(player_id=1, action_id=0)]
        raw = dict(game=dict(n_players=2, n_actions_per_player=[1, 1], round_robin=[0, 1, 0, 1],
            max_changes=1, menu_enabled=False, goals=[dict(goal_id=0, binary=True, required_actions=required),
            dict(goal_id=1, binary=False, required_actions=required)]), ego=0, own_preferences=[1, 1],
            type_catalogues={'0': [[1, 1]], '1': [[1, 1], [1, 0], [1, -1]]},
            background_prior=profile('balanced'))
        rules = PrivateInvestigationRules(raw)
        reference = FixedReference(rules, raw['background_prior'])
        full = PrivateWindow(rules, rules.initial(), rules.worlds, world_weights=reference.world_weights,
                             max_nodes=100000, seconds=30)
        for index, entry in enumerate(full.entries):
            if entry.actor is not None:
                full.policy[index] = reference.probabilities(entry.node)
        full.certificate = reference.certificate
        sparse = SparseWindow(reference, rules.initial(), 0, reference.world_weights, 3,
                              max_nodes=30000, seconds=30)
        self.assertLess(len(sparse.entries), len(full.entries) / 5)
        for k in (1, 2, 3):
            exact = window_values(full, 0, 0, reference.world_weights, k)
            compressed = window_values(sparse, 0, 0, reference.world_weights, k)
            for key in ('V_star', 'V_min', 'C_span', 'root_Q'):
                np.testing.assert_allclose(exact[key], compressed[key], atol=1e-9)
            for slot in ((1, 0), (1, 1)):
                args = dict(ego=0, root_index=0, root_weights=reference.world_weights, query_slot=slot, k=k)
                exact = masked_answer_value(full, **args)
                compressed = masked_answer_value(sparse, **args)
                self.assertAlmostEqual(exact['S'], compressed['S'])
                for variant in ('full', 'masked'):
                    self.assertAlmostEqual(exact[variant]['value'], compressed[variant]['value'])
                    np.testing.assert_allclose(exact[variant]['root_action_values'],
                                               compressed[variant]['root_action_values'], atol=1e-9)


if __name__ == '__main__':
    unittest.main()
