import random
import unittest
import numpy as np

from training.b_sft.social_b_oracle import BeliefOracle, canonical, forward_fixture
from training.b_sft.social_b_dataset import random_fixture
from training.b_sft.shared_teacher import SearchLimit


class RandomTieTests(unittest.TestCase):
    def test_sampling_does_not_randomize_inference(self):
        raw, prefix = forward_fixture()
        o = BeliefOracle(raw, prefix)
        own = o.worlds[-1][1]
        before = o.belief(1, 2)
        drawn = {canonical(o.sample_action(own, random.Random(seed))) for seed in range(40)}
        self.assertEqual(drawn, {canonical(a) for a in o.choices(own)['admissible_actions']})
        self.assertEqual(o.belief(1, 2), before)
        for action in o.choices(own)['admissible_actions']:
            child = BeliefOracle(raw, prefix)
            child.observe(action)
            self.assertIn(o.worlds[-1], child.worlds)

    def test_expected_values_integrate_all_random_branches(self):
        raw, prefix = forward_fixture(rounds=2)
        o = BeliefOracle(raw, prefix)
        tree = o.solve()
        branching = 0
        for i, entry in enumerate(tree.entries):
            if entry.actor is None: continue
            probs = tree.policy[i]
            np.testing.assert_allclose(probs.sum(axis=0), 1)
            for wi in range(tree.w):
                positive = probs[:, wi][probs[:, wi] > 0]
                np.testing.assert_allclose(positive, 1/len(positive))
                branching += len(positive) > 1
            for ids in tree.groups[entry.actor]:
                for wi in ids:
                    np.testing.assert_array_equal(probs[:, wi], probs[:, ids[0]])
        self.assertGreater(branching, 0)
        # Enumerate complete native public paths with probability products;
        # recompute leaf payoffs from commitments, not cached tree values.
        for wi, world in enumerate(tree.worlds):
            total = np.zeros(tree.n)
            stack = [(0, 1.0)]
            mass = 0
            while stack:
                i, prob = stack.pop(); entry = tree.entries[i]
                if entry.actor is None:
                    c = entry.node.state.snapshot_commitments()
                    flags = [all(c[a['player_id']][a['action_id']] for a in g['required_actions'])
                             for g in raw['game']['goals']]
                    total += prob * np.array([sum(v*f for v,f in zip(row, flags)) for row in world])
                    mass += prob
                else:
                    stack.extend((child, prob * tree.policy[i][a, wi]) for a,child in enumerate(entry.children)
                                 if tree.policy[i][a, wi] > 0)
            self.assertAlmostEqual(mass, 1)
            np.testing.assert_allclose(total, tree.values[0][wi])

    def test_full_rolling_path_is_invariant_to_action_order(self):
        raw, prefix = forward_fixture(rounds=2)
        target, goal = 1, 2
        a = BeliefOracle(raw, prefix)
        b = BeliefOracle(raw, prefix, reverse_actions=True)
        world = a.worlds[1]
        rng = random.Random(913)
        while not a.node.state.is_terminal:
            actor = a.rules.actor(a.node)
            for own in dict.fromkeys(w[actor] for w in a.worlds):
                left, right = a.choices(own), b.choices(own)
                self.assertEqual({canonical(x) for x in left['admissible_actions']},
                                 {canonical(x) for x in right['admissible_actions']})
            action = a.sample_action(world[actor], rng)
            a.observe(action); b.observe(action)
            self.assertEqual(a.worlds, b.worlds)
            self.assertIn(world, a.worlds)
            self.assertEqual(a.belief(target, goal), b.belief(target, goal))

    def test_nonconvergent_reference_is_not_preference_evidence(self):
        # v4 generation now uses 3--4 players and can hide the observer row.
        raw, prefix, target, goal = random_fixture(920035, hidden=1)
        for reverse in (False, True):
            o = BeliefOracle(raw, prefix, reverse_actions=reverse)
            before = (o.worlds, list(o.events), list(o.history))
            with self.assertRaisesRegex(SearchLimit, 'cycled'):
                o.observe({'action': 'PASS'})
            self.assertEqual((o.worlds, o.events, o.history), before)
            self.assertEqual(len(o.belief(target, goal)['possible_preferences']), 3)


if __name__ == '__main__':
    unittest.main()
