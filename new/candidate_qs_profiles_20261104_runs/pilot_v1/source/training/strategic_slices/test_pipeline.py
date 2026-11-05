"""Meaningful CPU checks of privacy, posterior, branches, grouping and recovery."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

import numpy as np
from .build import entrances, structural_family, select_slices
from .common import Dataset, VERSION, digest, file_hash, request, write_json, write_rows, save_reference
from training.b_sft.social_private_teacher import PrivateEpisode
from .runtime import Collector, Rollout, execute
from .evaluate import Evaluator
from .compare import compare
from .values import window_values


SMOKE = Path(__file__).resolve().parents[2] / 'new/local_data/strategic_slices_smoke_v1'


def fixture_dataset(folder):
    """Six explicit native test games, solved afresh; no generated corpus dependency."""
    fixture = Path(__file__).resolve().parents[2] / 'examples/strategic_slices/test_games.json'
    records = json.loads(fixture.read_text())
    config = dict(max_nodes=30000, max_k=3, entrance_trajectories=4, reach_epsilon=.25,
                  max_entrances=5, min_c=.1, min_increment=.05, min_s=.05, slices_per_parent=8)
    (folder / 'references').mkdir()
    parents = {s: [] for s in ('train', 'validation', 'test')}
    slices = {s: [] for s in parents}
    for row in records:
        raw, split = row['raw'], row['split']
        tree = PrivateEpisode(raw, seconds=30, max_nodes=30000, max_sweeps=128).tree
        pid = digest(raw)[:24]; filename = f'references/{pid}.npz'
        save_reference(folder / filename, tree)
        parents[split].append(dict(id=pid, raw=raw, players=tree.n, family=structural_family(raw['game']), split=split,
            world_weights=tree.world_weights.tolist(), reference_file=filename,
            reference_sha256=file_hash(folder / filename), certificate=tree.certificate))
        selected, _ = select_slices(tree, pid, row['seed'], config)
        slices[split].extend(dict(s, split=split) for s in selected)
    files = {}
    for split in parents:
        for kind, rows in [('parents', parents[split]), ('slices', slices[split])]:
            name = f'{split}_{kind}.jsonl'; write_rows(folder / name, rows)
            files[name] = dict(sha256=file_hash(folder / name), rows=len(rows))
    write_json(folder / 'manifest.json', dict(version=VERSION, config=config, files=files))
    write_json(folder / 'COMPLETE.json', dict(manifest_sha256=file_hash(folder / 'manifest.json')))
    return Dataset(folder, ('train', 'validation', 'test'))


def mock_generate(requests):
    """A seeded legal actor; tiny synthetic IDs exercise the collector, not an LLM."""
    outputs = []
    for req in requests:
        indices = req['tools'][0]['function']['parameters']['properties']['action_index']['enum']
        index = int(np.random.default_rng(req['seed']).choice(indices))
        outputs.append(dict(prompt_ids=[1, 2], response_ids=[3, 4, 5], behavior_log_probs=[-.3, -.4, -.5],
            request=deepcopy(req), completion=dict(finish_reason='stop', raw_message=dict(tool_calls=[dict(
                function=dict(name='act', arguments=json.dumps(dict(action_index=index))))]))))
    return outputs


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.dataset = fixture_dataset(Path(cls.temporary.name))

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_structural_family_ignores_player_action_goal_names(self):
        game = deepcopy(self.dataset.parents['train'][0]['raw']['game'])
        renamed = deepcopy(game)
        n = game['n_players']; mapping = list(reversed(range(n)))
        counts = [0] * n
        for p in range(n):
            counts[mapping[p]] = game['n_actions_per_player'][p]
        renamed['n_actions_per_player'] = counts
        renamed['round_robin'] = [mapping[p] for p in game['round_robin']]
        for g in renamed['goals']:
            for a in g['required_actions']:
                p = a['player_id']; a['action_id'] = game['n_actions_per_player'][p] - 1 - a['action_id']; a['player_id'] = mapping[p]
        renamed['goals'].reverse()
        for index, goal in enumerate(renamed['goals']):
            goal['goal_id'] = index
        self.assertEqual(structural_family(game), structural_family(renamed))

    def test_dataset_split_and_train_never_loads_test(self):
        data = Dataset(self.dataset.root)
        self.assertNotIn('test', data.parents)
        self.assertEqual({p['id'] for p in data.parents['train']}, {s['parent_id'] for s in data.slices['train']})
        self.assertFalse({p['family'] for p in data.parents['train']} & {p['family'] for p in self.dataset.parents['test']})

    def test_reference_roundtrip_and_three_player_exact_values(self):
        p = next(p for p in self.dataset.parents['train'] if p['players'] == 3)
        tree = self.dataset.tree(p)
        s = next(s for s in self.dataset.slices['train'] if s['parent_id'] == p['id'])
        values = window_values(tree, s['ego'], s['root_index'], s['entry_world_weights'], s['k'])
        self.assertAlmostEqual(values['C_span'], s['C_span'])
        self.assertGreater(values['C_span'], .1)

    def test_exact_span_compares_contingent_policies_without_hidden_world_access(self):
        worlds = (((1,), (1,)), ((1,), (-1,)))
        node = SimpleNamespace(worlds=worlds, state=SimpleNamespace(transcript=[]))
        entries = [SimpleNamespace(actor=0, node=node, actions=('A', 'B'), children=(1, 2)),
                   SimpleNamespace(actor=0, node=node, actions=('a0', 'a1'), children=(3, 4)),
                   SimpleNamespace(actor=0, node=node, actions=('b0', 'b1'), children=(5, 6))]
        for payoff in ([5, -1], [1, 1], [0, 4], [3, 3]):
            entries.append(SimpleNamespace(actor=None, node=node, children=(), payoff=np.array([[payoff[0], 0], [payoff[1], 0]])))
        tree = SimpleNamespace(worlds=worlds, entries=entries, policy=[np.full((2, 2), .5)] * 3 + [None] * 4)
        one = window_values(tree, 0, 0, [.5, .5], 1)
        two = window_values(tree, 0, 0, [.5, .5], 2)
        self.assertEqual((one['V_star'], one['V_min'], one['C_span']), (2.5, 1.5, 1.))
        # Exhaustively: A has continuation means {2,1}; B has {2,3}.
        # A clairvoyant optimizer would incorrectly get A=(5+1)/2=3.
        self.assertEqual((two['V_star'], two['V_min'], two['C_span']), (3., 1., 2.))

    def test_entry_posterior_matches_independent_history_likelihood(self):
        p = self.dataset.parents['train'][0]; tree = self.dataset.tree(p)
        for entrance in entrances(tree, 17, trajectories=4):
            masses = tree.world_weights.copy(); index = 0
            for ai in entrance['history']:
                masses *= .75 * tree.policy[index][ai] + .25 / len(tree.entries[index].actions)
                index = tree.entries[index].children[ai]
            for wi, world in enumerate(tree.worlds):
                if list(world[entrance['ego']]) != entrance['own'] or any(world[p][g] != v for p, g, v in entrance['private_results']):
                    masses[wi] = 0
            masses /= masses.sum()
            np.testing.assert_allclose(masses, entrance['entry_world_weights'])
            self.assertEqual(index, entrance['root_index'])

    def test_hidden_truth_does_not_change_same_information_prompt(self):
        for parent in self.dataset.parents['train']:
            rules = self.dataset.rules(parent); node = rules.initial(); actor = rules.actor(node)
            pairs = [(a, b) for a in rules.worlds for b in rules.worlds if a != b and a[actor] == b[actor]]
            if pairs:
                a, b = pairs[0]
                self.assertEqual(request(rules, node, a, 42), request(rules, node, b, 42))
                return
        self.fail('No uncertain partner fixture')

    def test_budget_recovery_and_per_trajectory_weighting_both_arms(self):
        for arm in ('slices', 'selfplay'):
            collector = Collector(self.dataset, mock_generate, arm, replicas=4)
            rows, units, games, metrics = collector.collect(0, arm, token_target=25)
            self.assertGreaterEqual(metrics['generated_tokens'], 25)
            self.assertEqual(sum(len(r['response_ids']) for r in rows), metrics['generated_tokens'])
            shares = {}
            for row in rows:
                shares[row['unit']] = shares.get(row['unit'], 0.) + row['loss_weight'] / len(rows)
            np.testing.assert_allclose(list(shares.values()), [1 / len(units)] * len(units))
            restored = Collector(self.dataset, mock_generate, arm, replicas=4)
            restored.restore(collector.state)
            self.assertEqual(collector.collect(1, arm, 25), restored.collect(1, arm, 25))

    def test_invalid_group_never_invents_terminal_reward_or_task_advantage(self):
        for arm in ('slices', 'selfplay'):
            def fail_last(requests):
                out = mock_generate(requests)
                out[-1]['completion'] = dict(finish_reason='length', raw_message=dict(tool_calls=[]))
                return out
            collector = Collector(self.dataset, fail_last, arm)
            rows, units, games, metrics = collector.collect(0, arm, 1)
            self.assertTrue(any(g['terminal_utility'] is None for g in games))
            self.assertTrue(all(r['task_advantage'] == 0 for r in rows))
            self.assertTrue(any(r['protocol_advantage'] == -.2 for r in rows))

    def test_branch_state_is_from_chosen_action(self):
        for parent in self.dataset.parents['train']:
            rules = self.dataset.rules(parent); node = rules.initial()
            offer = next((i for i, a in enumerate(rules.actions(node)) if a.to_dict().get('action') == 'OFFER'), None)
            if offer is not None:
                a = Rollout(self.dataset, parent, 42, 0); b = Rollout(self.dataset, parent, 42, 0)
                a.step(0); b.step(offer)
                self.assertNotEqual(a.node.pending, b.node.pending)
                self.assertNotEqual(a.request(0)['messages'], b.request(0)['messages'])
                return
        self.fail('No native offer fixture')

    def test_frozen_evaluation_and_paired_comparison(self):
        report = Evaluator(self.dataset, mock_generate, split='test', repeats=1).run()
        self.assertEqual(report['metrics']['team']['all']['completion_rate'], 1.)
        self.assertEqual(len([g for g in report['games'] if g['mode'] == 'team']), len(self.dataset.parents['test']))
        report['protocol']['seed'] = 42
        with tempfile.TemporaryDirectory() as folder:
            paths = [Path(folder) / arm for arm in ('sp', 'slices')]
            for path in paths:
                path.mkdir(); write_rows(path / 'games.jsonl', report['games'])
                write_json(path / 'summary.json', {k: v for k, v in report.items() if k not in ('calls', 'games')})
                write_json(path / 'COMPLETE.json', report['protocol'])
            result = compare(*paths)
            self.assertEqual(result['paired_utility_completed_parent_macro']['team']['mean'], 0.)


if __name__ == '__main__':
    unittest.main()
