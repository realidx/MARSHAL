"""Evidence checks for the paired RR cutoff oracle diagnostic."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from training.b_sft.preference_contract import profile, world_weights
from training.b_sft.shared_teacher import SearchLimit
from training.b_sft.social_private_teacher import PrivateInvestigationRules, observed_slots
from .bounded import BoundedPrivateWindow
from .build import sample_parent
from .diagnose_bounded import count_bounded_nodes, diagnose, metric_entrances, uniform_prefix


def tiny_parent(seed, players, rounds):
    """Small native connected games, preserving actual RR and private queries."""
    return dict(game=dict(n_players=players, n_actions_per_player=[1] * players,
                          goals=[dict(goal_id=0, binary=True,
                                      required_actions=[dict(player_id=p, action_id=0) for p in range(players)])],
                          round_robin=list(range(players)) * rounds, max_changes=1, menu_enabled=False),
                ego=0, own_preferences=[1], type_catalogues={str(p): [[1]] for p in range(players)},
                background_prior=profile('balanced'))


class BoundedDiagnosticTest(unittest.TestCase):
    def test_prefix_is_same_reachable_rr_boundary_for_every_depth(self):
        for n in (2, 3):
            raw = sample_parent(20261002, n, 3)
            rules = PrivateInvestigationRules(raw)
            root, prefix = uniform_prefix(rules, 20261002)
            replay = rules.initial()
            probability = 1.
            for ai, action in zip(prefix['history'], prefix['actions']):
                actions = rules.actions(replay)
                self.assertEqual(action, actions[ai].to_dict())
                probability /= len(actions)
                replay = rules._apply(replay, actions[ai])
                self.assertNotIn('revealed_preference', action)
            self.assertEqual(root.state.public_state(), replay.state.public_state())
            self.assertEqual(root.state.turn_index, n)
            self.assertIsNone(root.pending)
            self.assertEqual(root.worlds, rules.worlds)
            self.assertTrue(prefix['public_posterior_equals_source_prior'])
            self.assertAlmostEqual(prefix['world_independent_public_likelihood'], probability)
            for rr in (1, 2):
                counted = count_bounded_nodes(rules, root, rr, horizon_mode='rr')
                self.assertEqual(counted['cutoff'], n + n * rr)
            # The 2-player sampled prefix includes a private query, but no
            # realized answer is used or publicly injected by the diagnostic.
            if n == 2:
                self.assertTrue(any(observed_slots(root, p) for p in range(n)))
                self.assertTrue(all(not row for row in root.state.private_results))

    def test_physical_counting_matches_complete_unfolded_native_tree(self):
        raw = tiny_parent(5, 2, 3)
        rules = PrivateInvestigationRules(raw)
        for phase_rr in (0, 1):
            root, _ = uniform_prefix(rules, 5, phase_rr)
            for rr in (1, 2):
                counted = count_bounded_nodes(rules, root, rr)
                tree = BoundedPrivateWindow(rules, root, rules.worlds, lookahead_rr=rr,
                                            max_nodes=30000, seconds=10)
                self.assertEqual(counted['unfolded_public_history_nodes'], len(tree.entries))
                self.assertFalse(counted['strategy_transpositions_merged'])
                self.assertEqual(len(tree.entries) - 1, sum(len(e.children) for e in tree.entries))

    def test_root_cells_preserve_private_information_prior(self):
        raw = tiny_parent(0, 2, 3)
        raw['game']['goals'].append(dict(raw['game']['goals'][0], goal_id=1))
        raw['own_preferences'] = [1, 1]
        raw['type_catalogues'] = {'0': [[1, 1], [1, 0]], '1': [[1, 1], [1, -1]]}
        raw['background_prior'] = profile('want_heavy')
        rules = PrivateInvestigationRules(raw)
        prior = world_weights(rules.worlds, raw['background_prior'])
        tree = BoundedPrivateWindow(rules, rules.initial(), rules.worlds,
                                    world_weights=prior, lookahead_rr=1, seconds=10).solve()
        cells, counts = metric_entrances(tree, 0, dict(entrance_trajectories=2,
                                                    reach_epsilon=.25, max_entrances=2))
        roots = [c for c in cells if c.get('exhaustive_root_cell')]
        self.assertEqual(counts['exhaustive_root_cells'], 2)
        for cell in roots:
            mask = np.array([list(w[0]) == cell['own'] for w in tree.worlds])
            expected = prior * mask
            expected /= expected.sum()
            np.testing.assert_allclose(cell['entry_world_weights'], expected)

    def test_cpu_diagnostic_pairs_roots_and_records_verified_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'diagnostic'
            summary = diagnose(output, seeds=1, players=(2,), parent_rounds=3,
                               lookahead_rr=(1, 2), max_k=2, entrance_trajectories=2,
                               max_entrances=2, solver_seconds=10, parent_factory=tiny_parent)
            cases = [json.loads(line) for line in (output / 'cases.jsonl').read_text().splitlines()]
            self.assertEqual(len(cases), 4)
            self.assertEqual(summary['total_cases'], 4)
            self.assertTrue((output / 'COMPLETE.json').exists())
            for phase in ('initial', 'after_1rr'):
                pair = [row for row in cases if row['phase'] == phase]
                self.assertEqual(pair[0]['raw'], pair[1]['raw'])
                self.assertEqual(pair[0]['prefix'], pair[1]['prefix'])
                self.assertEqual(pair[0]['global_world_prior'], pair[1]['global_world_prior'])
                self.assertEqual(pair[0]['root_public_state'], pair[1]['root_public_state'])
            for row in cases:
                self.assertEqual(row['status'], 'measured')
                self.assertTrue(row['diagnostic_only'])
                self.assertTrue(row['training_reward_unspecified'])
                self.assertTrue(row['certificate']['verified'])
                self.assertTrue(row['certificate']['all_player_same_solver'])
                self.assertTrue(row['native_audit']['all_values_match'])
                self.assertEqual(row['nodes'], row['unfolded_public_history_nodes'])
                self.assertGreater(row['measured_entrances'], 0)
                self.assertIn('0.1', row['above_threshold'])
            for group in summary['groups']:
                self.assertEqual(group['attempted_parents'], 1)
                self.assertEqual(group['accepted_signal_parent_denominator'], 1)

    def test_resource_failure_has_no_fake_certificate_or_zero_signal(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'too-large'
            summary = diagnose(output, seeds=1, players=(2,), parent_rounds=3,
                               lookahead_rr=(1,), max_nodes=1, parent_factory=tiny_parent)
            cases = [json.loads(line) for line in (output / 'cases.jsonl').read_text().splitlines()]
            for row in cases:
                self.assertEqual(row['status'], 'unavailable')
                self.assertEqual(row['failure_stage'], 'preflight')
                self.assertEqual(row['failure_kind'], 'node_budget')
                self.assertIsNone(row['certificate'])
                self.assertFalse(row['strategy_tree_constructed'])
                self.assertNotIn('max_C_span', row)
                self.assertNotIn('max_private_S', row)
            for group in summary['groups']:
                self.assertEqual(group['accepted_signal_parent_denominator'], 0)
                self.assertEqual(group['measured_entrance_denominator'], 0)
        with tempfile.TemporaryDirectory() as temporary:
            with patch('training.strategic_slices.diagnose_bounded.BoundedPrivateWindow.solve',
                       side_effect=SearchLimit('Private teacher policy iteration cycled; no certified label')):
                output = Path(temporary) / 'cycling'
                diagnose(output, seeds=1, players=(2,), parent_rounds=3,
                         lookahead_rr=(1,), parent_factory=tiny_parent)
                cases = [json.loads(line) for line in (output / 'cases.jsonl').read_text().splitlines()]
                for row in cases:
                    self.assertEqual(row['failure_stage'], 'solve')
                    self.assertEqual(row['failure_kind'], 'policy_cycle')
                    self.assertIsNone(row['certificate'])
                    self.assertNotIn('entrances', row)

    def test_unfinished_policy_iteration_is_a_sweep_failure_without_labels(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'one-sweep'
            diagnose(output, seeds=1, players=(2,), parent_rounds=3,
                     lookahead_rr=(1,), max_sweeps=1, parent_factory=tiny_parent,
                     horizon_mode='rr', solver_mode='synchronous')
            cases = [json.loads(line) for line in (output / 'cases.jsonl').read_text().splitlines()]
            for row in cases:
                self.assertEqual(row['failure_stage'], 'solve')
                self.assertEqual(row['failure_kind'], 'sweep_budget')
                self.assertIsNone(row['certificate'])
                self.assertNotIn('max_C_span', row)

    def test_new_horizon_counts_return_action_and_clamps_at_terminal(self):
        rules = PrivateInvestigationRules(tiny_parent(0, 2, 3))
        root = rules.initial()
        old = count_bounded_nodes(rules, root, 1, horizon_mode='rr')
        new = count_bounded_nodes(rules, root, 1)
        self.assertEqual(old['cutoff'], 2)
        self.assertEqual(new['cutoff'], 3)
        self.assertEqual(new['next_own_proposal_index'], 2)
        self.assertTrue(new['next_own_proposal_included'])
        self.assertEqual(new['actual_proposal_turns'], 3)
        self.assertGreater(new['unfolded_public_history_nodes'], old['unfolded_public_history_nodes'])
        later, _ = uniform_prefix(rules, 0, 2)
        short = count_bounded_nodes(rules, later, 1)
        self.assertEqual(short['cutoff'], len(rules.spec.round_robin))
        self.assertEqual(short['actual_proposal_turns'], 2)
        self.assertFalse(short['next_own_proposal_included'])

    def test_exact_replay_reports_reuse_without_duplicate_signal_denominators(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'replay'
            summary = diagnose(output, seeds=1, players=(2,), parent_rounds=3,
                               lookahead_rr=(1,), max_k=1, entrance_trajectories=1,
                               max_entrances=0, solver_seconds=10, cache_replay=True,
                               parent_factory=tiny_parent)
            cases = [json.loads(line) for line in (output / 'cases.jsonl').read_text().splitlines()]
            self.assertEqual(summary['total_cases'], 2)
            self.assertEqual(summary['cache']['hits'], 2)
            self.assertEqual(summary['cache']['misses'], 2)
            self.assertGreater(summary['cache']['avoided_recomputation_source_seconds'], 0)
            for row in cases:
                self.assertEqual(row['status'], 'measured')
                self.assertEqual(row['actual_proposal_turns'], 3)
                self.assertTrue(row['next_own_proposal_included'])
                self.assertTrue(row['cache_replay']['exact_problem_cache_hit'])
                self.assertTrue(row['certificate']['verified'])
                self.assertEqual(row['sampling']['measured_sampled_cells'], 0)
                self.assertTrue(all(metric['entrance']['exhaustive_root_cell']
                                    for metric in row['entrances']))
            self.assertTrue(all(group['attempted_parents'] == 1 for group in summary['groups']))


if __name__ == '__main__':
    unittest.main()
