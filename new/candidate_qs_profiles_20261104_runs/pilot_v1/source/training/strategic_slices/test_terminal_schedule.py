"""Monitoring boundaries and larger frozen-policy collection, without GPUs."""
from copy import deepcopy
import ast
from contextlib import nullcontext
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest

from .terminal_training_schedule import due


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        self.options=dict(eval_every=None,save_every=None,eval_every_tokens=500_000,save_every_tokens=1_000_000)
        self.state=NS(kv={})

    def test_token_boundaries_independent_of_update_count_and_resume(self):
        self.assertFalse(due(self.options,self.state,'eval',999,499_999))
        self.assertTrue(due(self.options,self.state,'eval',1,500_001))
        self.state.kv['terminal_last_validation_tokens']=500_001
        self.assertFalse(due(self.options,self.state,'eval',2,950_000))
        self.assertTrue(due(self.options,self.state,'eval',2,1_100_000))
        # Crossing two buckets still produces one evaluation of this actor.
        self.state.kv['terminal_last_validation_tokens']=1_600_000
        restored=NS(kv=deepcopy(self.state.kv))
        self.assertFalse(due(self.options,restored,'eval',3,1_700_000))
        self.assertTrue(due(self.options,restored,'eval',4,2_000_000))

    def test_save_is_independent_and_best_save_does_not_move_absolute_boundary(self):
        self.assertTrue(due(self.options,self.state,'eval',0,600_000))
        self.assertFalse(due(self.options,self.state,'save',0,600_000))
        self.state.kv['terminal_last_checkpoint_tokens']=600_000
        self.assertTrue(due(self.options,self.state,'save',1,1_000_000))
        self.state.kv['terminal_last_checkpoint_tokens']=1_100_000
        self.assertFalse(due(self.options,self.state,'save',2,1_500_000))
        self.assertTrue(due(self.options,self.state,'save',3,2_000_000))

    def test_explicit_smoke_update_cadences_are_independent(self):
        self.options.update(eval_every=1,save_every=3)
        self.assertTrue(due(self.options,self.state,'eval',0,1))
        self.assertFalse(due(self.options,self.state,'save',0,1))
        self.assertTrue(due(self.options,self.state,'save',2,1))

    def test_node_budget_drains_without_changing_chain_sampling_across_batches(self):
        from .test_terminal_training import TrainingTests
        from .terminal_training import Collector,mock_generate
        TrainingTests.setUpClass()
        rows=[]
        for i in range(25):
            row=deepcopy(TrainingTests.rows[i%len(TrainingTests.rows)])
            row['id']=f'fixture-{i}';rows.append(row)
        data=NS(sha='fixture',train=rows,reference=lambda _:(TrainingTests.tree,{}))
        large=Collector(data,mock_generate,node_groups_per_update=20,replicas=8,concurrency=32)
        small=Collector(data,mock_generate,node_groups_per_update=1,replicas=8,concurrency=8)
        small_step=0
        for step in range(3):
            calls,units,games,metrics=large.collect(step,'slices',1)
            expected=[]
            for _ in games:
                expected.extend(small.collect(small_step,'slices',1)[2]);small_step+=1
            self.assertEqual(games,expected)
            self.assertTrue(20<=metrics['groups']<=22)
            self.assertEqual(large.state['cursor'],small.state['cursor'])
            self.assertEqual(large.state['exposure'],small.state['exposure'])
            for unit in units:
                weight=sum(c['loss_weight'] for c in calls if c['group']==unit['group'])/len(calls)
                self.assertAlmostEqual(weight,1/len(units))
        self.assertGreater(large.state['cursor'],25) # actually crossed a shuffle cycle
        restored=Collector(data,mock_generate,node_groups_per_update=20,replicas=8,concurrency=32)
        restored.restore(large.state)
        self.assertEqual(large.collect(3,'slices',1),restored.collect(3,'slices',1))

    def test_production_loop_dispatches_token_hooks_and_forces_final_and_pause_save(self):
        # Execute the real loop without importing the unavailable Ray runtime.
        import torch
        parsed=ast.parse((Path(__file__).parents[1]/'social_mixed/pipeline.py').read_text())
        klass=next(n for n in parsed.body if isinstance(n,ast.ClassDef) and n.name=='SocialPipeline')
        method=next(n for n in klass.body if isinstance(n,ast.FunctionDef) and n.name=='run')
        class Batch:
            def __init__(self):
                self.meta_info={}
                self.batch=dict(attention_mask=torch.ones(1,2),response_mask=torch.tensor([[0,1]]),
                    behavior_log_probs=torch.zeros(1,1))
            def __len__(self):return 1
            def __getitem__(self,index):return self
        scope=dict(torch=torch,json=json,deepcopy=deepcopy,make_batch=lambda *a,**k:Batch(),learning_rate=lambda *a:1e-6)
        exec(compile(ast.Module(body=[method],type_ignores=[]),'pipeline.py','exec'),scope)
        for paused in (False,True):
            with self.subTest(paused=paused),tempfile.TemporaryDirectory() as tmp:
                saved=[];validated=[]
                p=NS(root=Path(tmp),options=dict(self.options,total_tokens=1_200_000,recipe='strategic_slices',arm='slices',
                    pause_after_updates=7 if paused else None,max_behavior_logprob_delta=.05,max_behavior_clip_fraction=.01),
                    state=NS(step=-1,kv={},log_history=[]),stop_requested=False,
                    pipeline_config=NS(max_steps=100,actor_train=NS(strategy_args=NS(strategy_config={'tensor_model_parallel_size':1}))),
                    actor_train=NS(offload_states=lambda **k:None),actor_infer=NS(offload_states=lambda **k:None),
                    tokenizer=NS(pad_token_id=0),reference=None,tracker=NS(log=lambda *a,**k:None),
                    collector=NS(state={}),phase=lambda *a:nullcontext(),model_update=lambda *a:None)
                p.validation_due=lambda step,t:due(p.options,p.state,'eval',step,t)
                p.checkpoint_due=lambda step,t:due(p.options,p.state,'save',step,t)
                def collect(*args):
                    return [dict(prompt_ids=[1],response_ids=[2])],[],[],dict(generated_tokens=100_000,skip_optimizer=True)
                p.collector.collect=collect
                def log_probs(cluster,batch,key,**kwargs):batch.batch[key]=batch.batch['behavior_log_probs'].clone()
                p.log_probs=log_probs
                def save(step,force=False):
                    folder=p.root/'checkpoints'/f'checkpoint-{step}';folder.mkdir(parents=True,exist_ok=True)
                    if not (folder/'COMPLETE.json').exists():saved.append(step+1)
                    (folder/'COMPLETE.json').write_text('{}')
                    p.state.kv['terminal_last_checkpoint_tokens']=p.state.kv['training_response_tokens']
                def validate(step,tokens):
                    validated.append(step+1);p.state.kv['terminal_last_validation_tokens']=tokens
                p.save=save;p.validate=validate
                scope['run'](p)
                self.assertEqual(validated,[0,5] if paused else [0,5,10,12])
                self.assertEqual(saved,[7] if paused else [10,12])
                result=json.loads((p.root/'RESULT.json').read_text())
                self.assertEqual(result['status'],'early_gate' if paused else 'complete')


if __name__=='__main__':unittest.main()
