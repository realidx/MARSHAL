"""CPU checks for information isolation, control handoff, D and recovery."""
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from examples.strategic_slices.check_entry_information import restore
from .common import materialize_node, stable, write_json
from .oracle_consistent import measure_parent
from .terminal_d import (HTTPGenerator, TerminalRollout, load_config, mock_generate,
                         run_evaluation, summarize_slice)


class TerminalDTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        folder = Path(__file__).resolve().parents[2]/'examples/strategic_slices/fixtures'
        raw = json.loads((folder/'public_history_information.json').read_text())
        cls.tree = restore(raw, raw, folder/raw['reference_file'])
        cls.rows, _ = measure_parent(cls.tree, 'fixture', cap=8)
        for row in cls.rows:
            row.update(split='train', family='fixture', reference_id='fixture')
        cls.cfg = load_config()

    def finish(self, job):
        while job.status == 'running':
            req = job.request(self.cfg)
            job.accept(mock_generate([req])[0], req)
        return job.record()

    def test_controlled_decisions_and_terminal_continuation(self):
        tree = self.tree
        before = tree.reference_identity()[0]
        handoff = False
        for row in self.rows:
            for replica in range(8):
                job = TerminalRollout(tree, row, replica, 42)
                record = self.finish(job)
                self.assertEqual(record['status'], 'terminal')
                self.assertLessEqual(record['controlled_decisions'], row['k'])
                focal_model = [s for s in record['steps'] if s['source']=='model']
                self.assertTrue(all(s['actor']==row['ego'] for s in focal_model))
                self.assertEqual(len(focal_model), record['controlled_decisions'])
                count = 0
                for step in record['steps']:
                    count += step['source']=='model'
                    if step['actor']==row['ego'] and step['source']=='saved-reference':
                        self.assertEqual(count, row['k'])
                        handoff = True
                expected = tree.rules.terminal_payoffs(job.node, job.world)[row['ego']]
                self.assertEqual(record['utility'], expected)
        self.assertTrue(handoff)
        self.assertEqual(tree.reference_identity()[0], before)

    def test_hidden_world_is_not_in_visible_request(self):
        row = next(r for r in self.rows if sum(w>0 for w in r['members'][0]['world_weights'])>1)
        a = TerminalRollout(self.tree, row, 0, 42)
        b = TerminalRollout(self.tree, row, 0, 42)
        candidates = np.flatnonzero(np.asarray(a.member['world_weights'])>0)
        b.world_index = int(next(i for i in candidates if i!=a.world_index))
        b.world = self.tree.worlds[b.world_index]
        b.node = materialize_node(self.tree, b.index, b.world)
        self.assertNotEqual(a.world, b.world)
        self.assertEqual(a.request(self.cfg), b.request(self.cfg))
        visible = json.loads(a.request(self.cfg)['messages'][1]['content'])
        self.assertFalse({'root_Q','V_star','world_index','world','world_weights','certificate'} & set(visible))

    def test_response_entrances_and_private_answers_are_materialized(self):
        from training.b_sft.social_private_teacher import observed_slots
        found_response = False
        for row in self.rows:
            job = TerminalRollout(self.tree, row, 0, 42)
            found_response |= job.node.pending is not None
            for actor in range(self.tree.n):
                expected = tuple((p,g,job.world[p][g]) for p,g in observed_slots(job.node, actor))
                self.assertEqual(job.node.state.private_results[actor], expected)
        self.assertTrue(found_response)

    def test_invalid_and_truncated_are_not_terminal_rewards(self):
        row = self.rows[0]
        games = []
        for i in range(8):
            job = TerminalRollout(self.tree, row, i, 42)
            req = job.request(self.cfg)
            answer = mock_generate([req])[0]
            answer['completion']['finish_reason'] = 'length'
            job.accept(answer, req)
            games.append(job.record())
        summary = summarize_slice(row, games, 42)
        self.assertIsNone(summary['D'])
        self.assertIsNone(summary['D_completed_only']['mean'])
        self.assertEqual(summary['completed'], 0)
        self.assertTrue(all(g['utility'] is None for g in games))
        self.assertFalse(summary['sampled_reward_contrast'])
        job = TerminalRollout(self.tree, row, 0, 42)
        job.accept(dict(completion=dict(raw_message={}, finish_reason='stop')), job.request(self.cfg))
        self.assertEqual(job.status, 'invalid_action')

    def test_D_uses_mean_reward_and_does_not_clip_negative_estimates(self):
        row = self.rows[0]
        games = [dict(status='terminal', utility=row['V_star']+.2, utility_bounds=[-10,10], calls=[]) for _ in range(8)]
        result = summarize_slice(row, games, 42)
        self.assertAlmostEqual(result['D'], -.2)
        self.assertAlmostEqual(result['D_over_C'], -.2/row['C_span'])
        games[0].update(status='invalid_action', utility=None)
        result = summarize_slice(row, games, 42)
        self.assertIsNone(result['D'])
        self.assertEqual(result['D_completed_only']['n'], 7)
        self.assertLessEqual(result['D_missing_outcome_bounds'][0], result['D_missing_outcome_bounds'][1])

    def test_value_contrast_requires_same_prompt(self):
        row = self.rows[0]
        games = []
        for i in range(8):
            games.append(dict(status='terminal', utility=float(i%2), utility_bounds=[0,1], calls=[
                dict(prompt_sha256=str(i%2), action_index=i%2, first_action_oracle_gap=float(i%2))]))
        result = summarize_slice(row, games, 42)
        self.assertTrue(result['sampled_reward_contrast'])
        self.assertFalse(result['root_value_contrast'])
        for g in games:
            g['calls'][0]['prompt_sha256'] = 'same'
        self.assertTrue(summarize_slice(row, games, 42)['root_mixed_optimal_suboptimal'])

    def test_resume_reuses_only_atomic_completed_parents_and_rejects_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_json(root/'manifest.json', {'fixture':True})
            rows = []
            for pid in ('a','b'):
                for original in self.rows:
                    row = deepcopy(original); row.update(id=pid+row['id'], parent_id=pid)
                    rows.append(row)
            data = SimpleNamespace(root=root, parents={'a':{},'b':{}}, candidates=rows, reference=lambda _:self.tree)
            output = root/'result'
            identity = dict(mock=True, model=None)
            def interrupt_after_parent(requests):
                if (output/'parents/a.json').exists():
                    raise RuntimeError('simulated HTTP failure')
                return mock_generate(requests)
            with self.assertRaisesRegex(RuntimeError,'simulated HTTP'):
                run_evaluation(data, self.cfg, output, interrupt_after_parent, identity)
            self.assertTrue((output/'parents/a.json').exists())
            self.assertFalse((output/'parents/b.json').exists())
            summary = run_evaluation(data, self.cfg, output, mock_generate, identity, resume=True)
            self.assertEqual(summary['trajectories'], len(rows)*8)
            self.assertTrue(summary['mock'])
            def forbidden(_): self.fail('Completed run called model again')
            self.assertEqual(run_evaluation(data, self.cfg, output, forbidden, identity, resume=True), summary)
            with self.assertRaisesRegex(ValueError,'Resume protocol'):
                run_evaluation(data, dict(self.cfg, seed=99), output, forbidden, identity, resume=True)

    def test_subset_preserves_seeds_and_rejects_different_subset_on_resume(self):
        from .terminal_d import candidate_subset
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);write_json(root/'manifest.json',{'fixture':True})
            rows=[dict(self.rows[0],id='first',parent_id='p'),dict(self.rows[0],id='second',parent_id='p')]
            data=SimpleNamespace(root=root,parents={'p':{}},candidates=rows,reference=lambda _:self.tree)
            subset=candidate_subset(data,['first'])
            self.assertEqual(len(data.candidates),2)
            self.assertEqual(TerminalRollout(self.tree,rows[0],0,42).seed,
                             TerminalRollout(self.tree,subset.candidates[0],0,42).seed)
            identity=dict(mock=True,model=None)
            summary=run_evaluation(subset,self.cfg,root/'result',mock_generate,identity)
            self.assertEqual(summary['trajectories'],8)
            protocol=json.loads((root/'result/protocol.json').read_text())
            self.assertEqual(protocol['candidate_subset_ids'],['first'])
            other=candidate_subset(data,['second'])
            with self.assertRaisesRegex(ValueError,'Resume protocol'):
                run_evaluation(other,self.cfg,root/'result',mock_generate,identity,resume=True)
            with self.assertRaisesRegex(ValueError,'Unknown candidate'):
                candidate_subset(data,['absent'])
            with self.assertRaisesRegex(ValueError,'unique'):
                candidate_subset(data,['first','first'])

    def test_configured_subset_and_manifest_pin(self):
        from .terminal_d import load_configured_dataset
        from .common import file_hash
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_json(root/'manifest.json', {'fixture': True})
            write_json(root/'subset.json', {'requires_new_D': ['first']})
            write_json(root/'override.json', ['second'])
            data = SimpleNamespace(root=root, parents={'p': {}}, candidates=[
                {'id': 'first', 'parent_id': 'p'}, {'id': 'second', 'parent_id': 'p'}])
            cfg = dict(self.cfg, data=str(root), candidate_ids=str(root/'subset.json'),
                       dataset_sha256=file_hash(root/'manifest.json'))
            with patch('training.strategic_slices.terminal_d.load_dataset', return_value=data):
                self.assertEqual(load_configured_dataset(cfg).selected_candidate_ids, ['first'])
                self.assertEqual(load_configured_dataset(cfg, candidate_ids=root/'override.json').selected_candidate_ids, ['second'])
                with self.assertRaisesRegex(ValueError, 'manifest differs'):
                    load_configured_dataset(dict(cfg, dataset_sha256='wrong'))
            self.assertEqual(len(data.candidates), 2)

    def test_v4_serving_profile_keeps_refill_and_sampling(self):
        from .terminal_d import ROOT
        cfg = load_config(ROOT/'examples/strategic_slices/terminal_d_soc_v4_delta.json')
        self.assertEqual(cfg['workers'], 32)
        self.assertEqual(cfg['scheduler'], 'completion-refill-v1')
        self.assertEqual(cfg['max_tokens'], 4096)
        self.assertEqual({k:v for k,v in cfg.items() if k not in ('data','candidate_ids','dataset_sha256')},
                         {k:v for k,v in self.cfg.items() if k != 'data'})
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'config.json'
            write_json(path, dict(cfg, scheduler='refill-typo'))
            with self.assertRaisesRegex(ValueError, 'Unknown scheduler'):
                load_config(path)

    def test_http_payload_context_and_transport_errors(self):
        with tempfile.TemporaryDirectory() as temp:
            cfg = dict(self.cfg, context=self.cfg['max_tokens']+1024, workers=1)
            tokenizer = SimpleNamespace(apply_chat_template=lambda *a,**kw:dict(input_ids=[1,2,3]))
            client = HTTPGenerator('http://example.invalid/v1','fake',cfg,tokenizer,Path(temp)/'wire.jsonl')
            req = TerminalRollout(self.tree,self.rows[0],0,42).request(cfg)
            response = dict(choices=[dict(finish_reason='tool_calls',message=dict(tool_calls=[]))],
                            usage=dict(prompt_tokens=3,completion_tokens=4))
            with patch('training.strategic_slices.terminal_d.urlopen', return_value=io.BytesIO(json.dumps(response).encode())) as call:
                client([req])
                body = json.loads(call.call_args.args[0].data)
                self.assertEqual(body['model'],'fake')
                self.assertEqual(body['temperature'],.8)
                self.assertEqual(body['max_tokens'],self.cfg['max_tokens'])
                self.assertEqual(body['tools'][0]['function']['name'],'act')
            response['usage']['prompt_tokens']=4
            with patch('training.strategic_slices.terminal_d.urlopen', return_value=io.BytesIO(json.dumps(response).encode())):
                with self.assertRaisesRegex(ValueError,'prompt token mismatch'):
                    client([req])
            client.cfg = dict(cfg,context=cfg['max_tokens']+1)
            with patch('training.strategic_slices.terminal_d.urlopen') as call:
                with self.assertRaisesRegex(ValueError,'truncation is forbidden'):
                    client([req])
                call.assert_not_called()


if __name__ == '__main__':
    unittest.main()
