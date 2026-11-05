import ast
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

import torch
import yaml

from training.b_sft.social_bp_training import reward, native_completion, update_curriculum, level_weights, summarize, select_batch
from training.b_sft.bp_checkpoints import retain


def frozen():
    path = Path('new/local_data/social_runs/bp_soc_probe_r1/tasks.jsonl')
    if not path.exists(): path = Path('examples/social_bp/data/tasks.jsonl')
    return [json.loads(s) for s in path.read_text().splitlines()]


class TrainingSignalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.tasks = frozen()

    def test_all_frozen_gold_answers_still_native_and_correct(self):
        for t in self.tasks:
            with self.subTest(source=t['source'], variant=t['name_variant']):
                self.assertEqual(reward(t, native_completion(t))['reward'], 1)

    def test_actual_wrong_fullset_no_longer_beats_actual_truncation(self):
        tasks = {t['id']: t for t in self.tasks}
        path = Path('new/local_data/social_runs/bp_soc_download/846561.952bhmc2/local_scoring/scored_samples.jsonl')
        if not path.exists(): self.skipTest('Historical raw probe download is kept locally')
        samples = [json.loads(s) for s in path.read_text().splitlines()]
        failures = [s for s in samples if not s['score']['correct']]
        self.assertEqual(len(failures), 43)
        for s in failures: self.assertEqual(reward(tasks[s['task_id']], s)['reward'], 0)
        # Execute the real ROLL group-normalization function, not a rewritten
        # version. A group of wrong submissions/truncations must have zero PG.
        tree = ast.parse(Path('roll/utils/functionals.py').read_text())
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'group_reward_norm')
        scope = {'torch': torch}; exec(compile(ast.Module(body=[fn], type_ignores=[]), '<ROLL>', 'exec'), scope)
        d = SimpleNamespace(batch={'response_level_rewards': torch.zeros(8)})
        norm = scope['group_reward_norm'](d, n_sample=8).batch['response_level_rewards']
        self.assertTrue(torch.equal(norm, torch.zeros(8)))
        d.batch['response_level_rewards'] = torch.tensor([1.,0.,0.,0.,0.,0.,0.,0.])
        norm = scope['group_reward_norm'](d, n_sample=8).batch['response_level_rewards']
        self.assertGreater(norm[0].item(), 0); self.assertTrue(torch.all(norm[1:] < 0))

    def test_protocol_failure_is_zero_but_not_repaired(self):
        t = self.tasks[0]
        good = native_completion(t)
        ordinary = dict(raw_message=dict(content=good['raw_message']['tool_calls'][0]['function']['arguments']), finish_reason='stop')
        self.assertEqual(reward(t, ordinary)['status'], 'format_failure')
        self.assertEqual(reward(t, ordinary)['reward'], 0)
        self.assertIsNone(reward(t, dict(status='infrastructure_failure'))['reward'])
        self.assertEqual(reward(t, dict(good, finish_reason='length'))['reward'], 0)

    def test_invalid_investigation_target_is_not_accepted(self):
        t = next(t for t in self.tasks if t['task']=='P' and t['teacher']['acceptable_actions'][0].get('action')=='INVESTIGATE')
        c = native_completion(t)
        args = json.loads(c['raw_message']['tool_calls'][0]['function']['arguments']); args['player'] = 'Nonexistent'
        c['raw_message']['tool_calls'][0]['function']['arguments'] = json.dumps(args)
        self.assertEqual(reward(t, c)['reward'], 0)

    def test_b_and_p_progress_separately_and_need_two_validation_points(self):
        first = {'B/0': dict(count=16, accuracy=.8, contrast_accuracy=.7), 'P/0': dict(count=16, accuracy=.2, contrast_accuracy=.1)}
        state = update_curriculum(None, 0, first)
        state = update_curriculum(state, 10, first)
        self.assertEqual(state['allowed'], {'B': 0, 'P': 0})
        state = update_curriculum(state, 20, first)
        self.assertEqual(state['allowed'], {'B': 1, 'P': 0})
        self.assertEqual(level_weights(30, 'B', state), (.4,.5,.1))
        self.assertEqual(level_weights(30, 'P', state), (.7,.25,.05))

    def test_deteriorating_controls_prevent_progression(self):
        first = {'B/0': dict(count=16, accuracy=.8, contrast_accuracy=.8)}
        second = {'B/0': dict(count=16, accuracy=.9, contrast_accuracy=.2)}
        state = update_curriculum(None, 10, first)
        state = update_curriculum(state, 20, second)
        self.assertEqual(state['allowed']['B'], 0)

    def test_direct_truth_does_not_promote_behavior_curriculum(self):
        t = dict(task='B', pool='update', stage=0, direct_answer=True, contrast_group='x', answer_signature='y', id='z')
        result = summarize([dict(task=t, score=dict(correct=True, status='ok'))]*8)
        self.assertNotIn('B/0', result)
        self.assertEqual(result['B/update']['accuracy'], 1.)

    def test_critical_information_control_regression_prevents_progression(self):
        first = {'P/0':dict(count=32,accuracy=.8,contrast_accuracy=.6),'P/information_negative':dict(accuracy=.9)}
        second = {'P/0':dict(count=32,accuracy=.9,contrast_accuracy=.6),'P/information_negative':dict(accuracy=.5)}
        state = update_curriculum(update_curriculum(None,10,first),20,second)
        self.assertEqual(state['allowed']['P'],0)

    def test_native_finish_reason_preserved_without_eos_invention(self):
        source = ast.parse(Path('training/b_sft/social_bp_reward_worker.py').read_text())
        fn = next(n for n in source.body if isinstance(n,ast.FunctionDef) and n.name=='decode_ids')
        scope = {}; exec(compile(ast.Module(body=[fn],type_ignores=[]),'<decode>', 'exec'),scope)
        decode = scope['decode_ids']
        self.assertEqual(decode([5,6,0,0],2,'stop',4),([5,6],False))
        self.assertEqual(decode([5,6,7,8],4,'length',4),([5,6,7,8],True))
        with self.assertRaises(RuntimeError): decode([5,6],2,'abort',4)

    def test_frozen_dataset_split_and_semantic_integrity(self):
        from training.b_sft.social_bp_grpo import validate_tasks,read
        rows = read('examples/social_bp/data/tasks.jsonl')
        self.assertEqual(validate_tasks(rows)['tasks'],384)

    def test_ten_step_difficulty_quotas_and_balanced_information_exposure(self):
        from training.b_sft.social_bp_grpo import read
        rows = [t for t in read('examples/social_bp/data/tasks.jsonl') if t['split']=='train']
        for start, expected in ((0,[56,20,4]),(20,[32,40,8]),(60,[16,40,24])):
            counts = Counter()
            for step in range(start,start+10):
                selected = select_batch(rows,step,100,16,20260914,dict(allowed={'B':2,'P':2}))
                self.assertEqual(sum(t['task']=='B' for t in selected),8)
                self.assertEqual(sum(t.get('information_positive',False) for t in selected),1)
                self.assertLessEqual(sum(t['direct_answer'] for t in selected),1)
                counts.update((t['task'],t['stage']) for t in selected)
            for kind in ('B','P'): self.assertEqual([counts[kind,stage] for stage in range(3)],expected)

    def test_config_has_one_adam_update_per_rollout_and_no_auxiliary_rewards(self):
        c = yaml.safe_load(Path('examples/social_bp/grpo.yaml').read_text())
        tr = c['actor_train']['training_args']
        self.assertEqual(4*tr['per_device_train_batch_size']*tr['gradient_accumulation_steps'], 16*8)
        self.assertEqual(c['expected_actor_optimizer_steps_per_rollout'], 1)
        self.assertEqual(c['ppo_epochs'], 1)
        self.assertEqual(c['validation']['generating_args']['num_return_sequences'], 4)
        self.assertEqual(c['rewards']['social_bp']['response_length_penalty_coef'], 0)
        self.assertEqual(c['actor_infer']['generating_args']['repetition_penalty'], 1.)
        self.assertEqual(tr['optimizer_backend'], 'torch_adamw')

    def test_checkpoint_retention_preserves_best_weights_and_latest_two(self):
        pools = {'B': ('formation','maintain','update'), 'P': ('complete','uncertain','result_use','information')}
        def metrics(v): return {f'{k}/{p}': {'accuracy': v} for k, ps in pools.items() for p in ps}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); folder = root/'checkpoints'; folder.mkdir()
            for step, value in ((10,.8),(20,.6),(30,.5)):
                ck = folder/f'checkpoint-{step-1}'; ck.mkdir()
                (ck/'COMPLETE.json').write_text('{}'); (ck/'config.json').write_text('{}')
                (ck/'pytorch_model.bin').write_bytes(str(step).encode())
                (ck/'checkpoint').mkdir(); (ck/'checkpoint'/'optimizer.pt').write_bytes(b'optimizer')
                retain(root, step, metrics(value))
            self.assertEqual((root/'best_model'/'pytorch_model.bin').read_bytes(), b'10')
            self.assertFalse((root/'best_model'/'checkpoint').exists())
            self.assertEqual(sorted(p.name for p in folder.iterdir()), ['checkpoint-19','checkpoint-29'])


if __name__ == '__main__': unittest.main()
