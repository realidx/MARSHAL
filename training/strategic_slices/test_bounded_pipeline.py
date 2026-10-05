"""End-to-end checks of cutoff rewards, private information and full-game eval."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from .bounded import BoundedPrivateWindow, current_payoffs
from .bounded_data import BACKEND, CONTRACT, RecedingReference
from .build import measure_entrance, structural_family
from .common import Dataset, VERSION, digest, file_hash, save_reference, write_json, write_rows, replay_node
from .diagnose_bounded import root_entrances
from .runtime import Collector, Rollout, execute
from .evaluate import Evaluator
from .test_pipeline import mock_generate
from .test_bounded_solver import raw_game
from .batched_response import BatchedResponse
from training.b_sft.social_private_teacher import PrivateInvestigationRules
from training.b_sft.preference_contract import world_weights, profile

FIXTURE = Path(__file__).resolve().parents[2] / 'examples/strategic_slices/fixtures/information_acquisition.json'


def add_parent(folder, raw, history, split, config):
    rules = PrivateInvestigationRules(raw)
    prior = world_weights(rules.worlds, raw['background_prior'])
    settings = dict(lookahead_rr=config['lookahead_rr'], max_nodes=config['max_nodes'], seconds=90)
    tree = BoundedPrivateWindow(rules, replay_node(rules, history), rules.worlds,
                               world_weights=prior, **settings).solve()
    pid = digest(raw)[:24]; rid = digest((pid, history))[:24]
    name = f'references/{rid}.npz'; save_reference(folder / name, tree)
    record = dict(id=rid, history=history, settings=settings, world_weights=prior.tolist(),
        certificate=tree.certificate, native_audit=tree.audit_native(), reference_file=name,
        reference_sha256=file_hash(folder / name))
    slices = []
    for entrance in root_entrances(tree):
        entrance.update(history=history, reference_id=rid, absolute_cutoff=tree.cutoff,
                        entrance_policy='world-independent-uniform-native-v1')
        rows, _ = measure_entrance(tree, entrance, pid, config)
        slices.extend(dict(s, split=split) for s in rows)
    parent = dict(id=pid, family=structural_family(raw['game']), split=split, players=rules.spec.n_players,
        raw=raw, world_weights=prior.tolist(), reference_backend=BACKEND,
        bounded_references={rid: record}, slices=len(slices), seed=42)
    return parent, slices


def fixture_dataset(folder):
    (folder / 'references').mkdir()
    config = dict(reference_policy=BACKEND, max_nodes=400000, solver_seconds=90,
        lookahead_rr=1, max_k=3, min_c=.1, min_increment=.05, min_s=.05, reach_epsilon=1.)
    files = {}
    for split, rounds in [('train', 3), ('validation', 4), ('test', 5)]:
        parents, slices = [], []
        for players in (2, 3):
            raw = raw_game(players, rounds, binary=False)
            raw['background_prior'] = profile('balanced')
            parent, ss = add_parent(folder, raw, [], split, config)
            parents.append(parent); slices.extend(ss)
        if split == 'train':
            source = json.loads(FIXTURE.read_text())
            parent, ss = add_parent(folder, source['raw'], source['history'], split, dict(config, lookahead_rr=2))
            parents.append(parent); slices.extend(ss)
        for kind, rows in [('parents', parents), ('slices', slices)]:
            name = f'{split}_{kind}.jsonl'; write_rows(folder / name, rows)
            files[name] = dict(sha256=file_hash(folder / name), rows=len(rows))
    write_json(folder / 'manifest.json', dict(version=VERSION, config=config, files=files, training_contract=CONTRACT))
    write_json(folder / 'COMPLETE.json', dict(manifest_sha256=file_hash(folder / 'manifest.json')))
    return Dataset(folder, ('train', 'validation', 'test'))


class BoundedPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.data = fixture_dataset(Path(cls.temp.name))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_positive_free_choice_information_survives_length_selection(self):
        selected = [s for s in self.data.slices['train'] if s['information_positive']]
        self.assertTrue(selected)
        s = selected[0]
        self.assertEqual(s['k'], 2)
        self.assertAlmostEqual(max(q['S'] for q in s['information_values']), .25)
        p = self.data.by_id[s['parent_id']]
        # Same parent and legal entrance, shorter endpoint loses information value.
        r = self.data.rules(p)
        tree = BoundedPrivateWindow(r, replay_node(r, s['history']), r.worlds,
            world_weights=p['world_weights'], lookahead_rr=1, seconds=60).solve()
        short, _ = measure_entrance(tree, root_entrances(tree)[0], p['id'], self.data.manifest['config'])
        self.assertTrue(all(not item['information_positive'] for item in short))

    def test_slice_stops_at_cutoff_and_sp_reaches_native_terminal(self):
        p = self.data.parents['train'][0]
        s = next(s for s in self.data.slices['train'] if s['parent_id'] == p['id'])
        short = Rollout(self.data, p, 7, 0, s)
        full = Rollout(self.data, p, 7, 0)
        self.assertIn('evaluation_window', json.loads(short.request(1.)['messages'][1]['content']))
        self.assertNotIn('evaluation_window', json.loads(full.request(1.)['messages'][1]['content']))
        execute([short, full], mock_generate)
        self.assertEqual(short.status, 'cutoff')
        self.assertFalse(short.node.state.is_terminal)
        self.assertIsNone(short.node.pending)
        self.assertEqual(short.node.state.turn_index, s['absolute_cutoff'])
        self.assertEqual(short.utility, list(current_payoffs(short.rules, short.node, short.world)))
        self.assertIsNone(short.summary()['terminal_utility'])
        self.assertEqual(full.status, 'terminal')
        self.assertTrue(full.node.state.is_terminal)

    def test_private_information_prompt_is_not_realized_world(self):
        s = next(s for s in self.data.slices['train'] if s['information_positive'])
        p = self.data.by_id[s['parent_id']]
        requests = [Rollout(self.data, p, 7, wi, s).request(1.) for wi in range(len(p['world_weights']))]
        self.assertEqual(requests[0], requests[1])
        self.assertEqual(requests[1], requests[2])

    def test_both_collectors_and_deterministic_resume(self):
        for arm in ('slices', 'selfplay'):
            collector = Collector(self.data, mock_generate, arm)
            first = collector.collect(0, arm, 24)
            self.assertTrue(first[0])
            state = deepcopy(collector.state)
            again = Collector(self.data, mock_generate, arm); again.restore(state)
            a = collector.collect(1, arm, 24); b = again.collect(1, arm, 24)
            self.assertEqual(a, b)
            self.assertTrue(all(g['completed'] for g in a[2]))

    def test_complete_eval_and_slice_metrics_keep_separate_objectives(self):
        report = Evaluator(self.data, mock_generate, modes=('team', 'focal_reference', 'slices')).run()
        for mode in ('team', 'focal_reference'):
            self.assertEqual(report['metrics'][mode]['all']['completion_rate'], 1.)
            self.assertEqual(report['metrics'][mode]['all']['utility_scope'], 'native-terminal')
        self.assertEqual(report['metrics']['slices']['all']['utility_scope'], 'cutoff')
        self.assertTrue(all(g['terminal_utility'] is None for g in report['games'] if g['mode'] == 'slices'))

    def test_changed_cutoff_is_rejected(self):
        s = deepcopy(self.data.slices['train'][0]); s['absolute_cutoff'] += 1
        with self.assertRaisesRegex(ValueError, 'cutoff mismatch'):
            self.data.reference(self.data.by_id[s['parent_id']], s)

    def test_invalid_replica_disables_entire_task_group(self):
        def invalid_first(requests):
            outputs = mock_generate(requests)
            if outputs:
                outputs[0]['completion']['raw_message']['tool_calls'] = []
            return outputs
        rows, _, games, _ = Collector(self.data, invalid_first, 'slices').collect(0, 'slices', 12)
        self.assertTrue(any(not g['completed'] for g in games))
        self.assertTrue(all(r['task_advantage'] == 0 for r in rows))
        self.assertTrue(all(r['protocol_advantage'] == (-.2 if not r['valid'] else 0.) for r in rows))

    def test_receding_reference_updates_only_observed_public_likelihood(self):
        s = next(s for s in self.data.slices['train'] if s['information_positive'])
        ref = RecedingReference(self.data, self.data.by_id[s['parent_id']])
        prior = ref.weights.copy()
        likelihood = np.array([[.1, .2, .8], [.9, .8, .2]])
        ref.observe_reference(likelihood, 0)
        np.testing.assert_allclose(ref.weights, prior * likelihood[0] / (prior @ likelihood[0]))

    def test_mock_signal_probe_reports_actual_zero_variance_groups(self):
        from .signal_probe import probe
        def always_pass(requests):
            outputs = mock_generate(requests)
            for request, output in zip(requests, outputs):
                visible = json.loads(request['messages'][1]['content'])
                actions = visible['legal_actions']
                index = next((r['index'] for r in actions if r['action'].get('action') == 'PASS'), 0)
                output['completion']['raw_message']['tool_calls'][0]['function']['arguments'] = json.dumps(dict(action_index=index))
            return outputs
        report, rows, _ = probe(self.data, always_pass, 'selfplay', groups=2)
        self.assertEqual(report['active_group_fraction'], 0.)
        self.assertTrue(all(r['complete'] and r['reward_span'] == 0 for r in rows))

    def test_batched_candidate_best_responses_match_independent_scalar(self):
        s = next(s for s in self.data.slices['train'] if s['information_positive'])
        tree = deepcopy(self.data.reference(self.data.by_id[s['parent_id']], s))
        rng = np.random.default_rng(123)
        for i, groups in tree.information_groups.items():
            for ids in groups:
                probs = rng.dirichlet(np.ones(len(tree.entries[i].actions)))
                tree.policy[i][:, ids] = probs[:, None]
        engine = BatchedResponse(tree)
        for player in range(tree.n):
            scalar, sv = tree.response(player); batched, bv = engine.response(player)
            np.testing.assert_allclose(sv, bv, atol=1e-12)
            for index in scalar:
                np.testing.assert_allclose(scalar[index], batched[index], atol=1e-12)


if __name__ == '__main__':
    unittest.main()
