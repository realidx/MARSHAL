"""Final-test lifecycle and real native rollout checks without GPU initialization."""
from contextlib import nullcontext
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest

from .terminal_training import mock_generate
from .terminal_training_evaluate import Validator
from .terminal_training_final_test import run_final_test
from .common import write_json


class FinalTestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from .test_terminal_d import TerminalDTests
        TerminalDTests.setUpClass()
        cls.tree=TerminalDTests.tree
        cls.cfg=dict(TerminalDTests.cfg,max_tokens=1024)
        raw=json.loads((Path(__file__).resolve().parents[2]/'examples/strategic_slices/fixtures/public_history_information.json').read_text())['raw']
        parents={split:dict(id=split,family='fixture',players=3,raw=raw,split=split) for split in ('validation','test')}
        def rows(split,count):
            return [dict(deepcopy(row),id=split+'-'+row['id'],parent_id=split,split=split)
                for row in TerminalDTests.rows[:count]]
        cls.data=NS(sha='fixture',validation=rows('validation',1),test=rows('test',2),parents=parents,
            reference=lambda row:(cls.tree,{}))

    def pipeline(self,root):
        root=Path(root);checkpoint=root/'checkpoints/checkpoint-2'
        checkpoint.mkdir(parents=True);write_json(checkpoint/'COMPLETE.json',dict(verified=True))
        (root/'LAST_CHECKPOINT').write_text(str(checkpoint))
        write_json(root/'RESULT.json',dict(status='complete',training_response_tokens=100,updates=3))
        events=[]
        def generate(requests):
            self.assertIn('sync',events)
            events.append('generate');return mock_generate(requests)
        return NS(root=root,state=NS(step=2),stop_requested=False,
            collector=NS(dataset=self.data,cfg=self.cfg),options=dict(total_tokens=100,test_repeats=2,validation_limit=1),
            generate=generate,phase=lambda _:nullcontext(),model_update=lambda _:events.append('sync'),
            actor_train=NS(offload_states=lambda **_:events.append('offload_train')),
            actor_infer=NS(offload_states=lambda **_:events.append('offload_infer')),events=events)

    def test_test_split_full_roles_seeds_and_output_budget(self):
        requests=[]
        def generate(batch):requests.extend(batch);return mock_generate(batch)
        a=Validator(self.data,generate,self.cfg,repeats=2,split='test').run()
        b=Validator(self.data,mock_generate,self.cfg,repeats=2,split='test').run()
        self.assertEqual(a,b)
        self.assertEqual(a['slices']['episodes'],4)
        self.assertTrue(a['protocol']['test_loaded_for_scoring'])
        self.assertEqual({r['parent_id'] for r in a['slice_games']},{'test'})
        self.assertEqual(a['full_games']['protocol']['split'],'test')
        self.assertEqual(a['full_games']['metrics']['team']['all']['episodes'],2)
        self.assertEqual(a['full_games']['metrics']['focal_reference']['all']['episodes'],6)
        self.assertEqual({r['focal'] for r in a['full_games']['games'] if r['mode']=='focal_reference'},{0,1,2})
        self.assertTrue(all(r['max_tokens']==1024 and r['temperature']==0 for r in requests))
        self.assertEqual(a['generated_response_tokens'],2*len(requests))
        validation=Validator(self.data,mock_generate,self.cfg).run()
        self.assertFalse(validation['protocol']['test_loaded_for_scoring'])
        self.assertEqual({r['parent_id'] for r in validation['slice_games']},{'validation'})

    def test_final_checkpoint_sync_completion_and_no_duplicate_scoring(self):
        with tempfile.TemporaryDirectory() as root:
            p=self.pipeline(root);run_final_test(p)
            result=json.loads((p.root/'RESULT.json').read_text())
            report=json.loads((p.root/'test/report.json').read_text())
            self.assertEqual(result['final_test']['status'],'complete')
            self.assertEqual(result['training_response_tokens'],100)
            self.assertEqual(report['slices']['episodes'],4) # validation_limit must not trim test
            self.assertFalse(report['used_for_checkpoint_selection'])
            self.assertEqual(report['final_checkpoint']['optimizer_step'],2)
            self.assertTrue((p.root/'test/COMPLETE.json').is_file())
            events=list(p.events);run_final_test(p)
            self.assertEqual(p.events,events)
            (p.root/'test/report.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'identity/report changed'):run_final_test(p)

    def test_paused_interrupted_or_budget_incomplete_does_not_test(self):
        for status,consumed,stop in (('paused',100,False),('early_gate',100,False),
                ('step_limit_before_token_budget',90,False),('complete',90,False),('complete',100,True)):
            with self.subTest(status=status,consumed=consumed,stop=stop),tempfile.TemporaryDirectory() as root:
                p=self.pipeline(root);p.stop_requested=stop
                write_json(p.root/'RESULT.json',dict(status=status,training_response_tokens=consumed))
                run_final_test(p)
                self.assertEqual(p.events,[])
                self.assertFalse((p.root/'test/COMPLETE.json').exists())
                self.assertEqual(json.loads((p.root/'RESULT.json').read_text())['final_test']['status'],'not_run')

    def test_test_interruption_and_retry_preserve_trained_checkpoint(self):
        with tempfile.TemporaryDirectory() as root:
            p=self.pipeline(root);normal=p.generate
            def interrupted(requests):
                p.stop_requested=True;return normal(requests)
            p.generate=interrupted;run_final_test(p)
            self.assertFalse((p.root/'test/COMPLETE.json').exists())
            self.assertEqual(json.loads((p.root/'RESULT.json').read_text())['final_test']['status'],'interrupted')
            self.assertTrue((p.root/'checkpoints/checkpoint-2/COMPLETE.json').exists())
            p.stop_requested=False;p.generate=normal;run_final_test(p)
            self.assertEqual(json.loads((p.root/'RESULT.json').read_text())['final_test']['status'],'complete')

    def test_infrastructure_failure_cannot_look_like_completed_test(self):
        with tempfile.TemporaryDirectory() as root:
            p=self.pipeline(root)
            def failed(_):raise RuntimeError('backend failed')
            p.generate=failed
            with self.assertRaisesRegex(RuntimeError,'backend failed'):run_final_test(p)
            self.assertFalse((p.root/'test/COMPLETE.json').exists())
            self.assertEqual(json.loads((p.root/'RESULT.json').read_text())['final_test']['status'],'failed')
            self.assertEqual(p.events[-1],'offload_infer')


if __name__=='__main__':unittest.main()
