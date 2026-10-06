"""Check best/final selection and retention on isolated temporary checkpoints."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from .common import write_json
from .terminal_training_checkpoints import select_best,retain_checkpoints,finalize_checkpoints


class CheckpointTests(unittest.TestCase):
    def pipeline(self,root,best=None):
        p=NS(root=Path(root),state=NS(step=-1,kv={}))
        if best:p.state.kv['best_validation']=deepcopy(best)
        def save(step,force=False):
            p.state.step=step
            folder=p.root/'checkpoints'/f'checkpoint-{step}';folder.mkdir(parents=True,exist_ok=True)
            write_json(folder/'COMPLETE.json',dict(step=step))
            write_json(folder/'state.json',p.state.kv)
            retain_checkpoints(p)
        p.save=save;return p

    def score(self,p,step,value,split='validation'):
        select_best(p,dict(protocol=dict(split=split),slices=dict(full_window_success_rate=value)),step,(step+1)*100)

    def completed(self,p):return {int(f.name.split('-')[-1]) for f in (p.root/'checkpoints').glob('checkpoint-*')}

    def final(self,p,step):
        p.save(step)
        (p.root/'LAST_CHECKPOINT').write_text(str(p.root/'checkpoints'/f'checkpoint-{step}'))
        write_json(p.root/'RESULT.json',dict(status='complete'))
        finalize_checkpoints(p)
        return json.loads((p.root/'CHECKPOINTS.json').read_text())

    def test_final_lower_than_best_retains_exactly_two(self):
        with tempfile.TemporaryDirectory() as root:
            p=self.pipeline(root)
            self.score(p,-1,1.) # Base model is a monitor, not a trained checkpoint.
            self.assertFalse(p.state.kv)
            self.score(p,9,.8)
            self.score(p,19,.5);p.save(19)
            self.assertEqual(self.completed(p),{9,19})
            self.score(p,29,.6);record=self.final(p,29)
            self.assertEqual(self.completed(p),{9,29})
            self.assertEqual(record['unique_checkpoints'],2)
            self.assertTrue(record['best'].endswith('checkpoint-9'))
            self.assertTrue(record['final'].endswith('checkpoint-29'))

    def test_final_best_or_tied_best_keeps_one(self):
        for value in (.8,.9):
            with self.subTest(value=value),tempfile.TemporaryDirectory() as root:
                p=self.pipeline(root)
                self.score(p,9,.8)
                self.score(p,19,.4);p.save(19)
                self.score(p,29,value);record=self.final(p,29)
                self.assertEqual(self.completed(p),{29})
                self.assertEqual(record['best'],record['final'])
                self.assertEqual(record['unique_checkpoints'],1)
                state=json.loads((p.root/'checkpoints/checkpoint-29/state.json').read_text())
                self.assertEqual(state['best_validation']['step'],29)

    def test_cannot_select_on_test_or_finalize_unevaluated_final(self):
        with tempfile.TemporaryDirectory() as root:
            p=self.pipeline(root)
            with self.assertRaisesRegex(ValueError,'never test'):self.score(p,9,.9,'test')
            self.score(p,9,.5)
            with self.assertRaisesRegex(ValueError,'must be evaluated'):self.final(p,19)

    def test_resume_preserves_inherited_best_without_deleting_earlier_run(self):
        with tempfile.TemporaryDirectory() as root:
            old=self.pipeline(Path(root)/'old');self.score(old,9,.8)
            p=self.pipeline(Path(root)/'new',old.state.kv['best_validation'])
            self.score(p,19,.4);p.save(19)
            self.score(p,29,.5);record=self.final(p,29)
            self.assertEqual(self.completed(p),{29})
            self.assertEqual(self.completed(old),{9})
            self.assertEqual(record['unique_checkpoints'],2)
            self.assertEqual(Path(record['best']).parent.parent,old.root.resolve())

    def test_production_save_rebinds_resumed_best_final_to_one_local_copy(self):
        import ast
        import torch
        parsed=ast.parse((Path(__file__).parent/'terminal_training_pipeline.py').read_text())
        klass=next(n for n in parsed.body if isinstance(n,ast.ClassDef))
        class Base:
            def save(self,step,force=False):
                folder=self.root/'checkpoints'/f'checkpoint-{step}'
                folder.mkdir(parents=True,exist_ok=True)
                write_json(folder/'COMPLETE.json',dict(step=step))
                write_json(folder/'state.json',self.state.kv)
        scope=dict(SocialPipeline=Base,torch=torch,Path=Path,retain_checkpoints=retain_checkpoints)
        exec(compile(ast.Module(body=[klass],type_ignores=[]),'terminal_training_pipeline.py','exec'),scope)
        with tempfile.TemporaryDirectory() as root:
            old=self.pipeline(Path(root)/'old');self.score(old,9,.8)
            p=scope['TerminalPipeline']();p.root=Path(root)/'new'
            p.state=NS(step=9,kv=deepcopy(old.state.kv))
            p.save(9,force=True)
            self.assertEqual(Path(p.state.kv['best_validation']['checkpoint']),
                (p.root/'checkpoints/checkpoint-9').resolve())
            self.assertEqual(self.completed(p),{9})
            self.assertEqual(self.completed(old),{9})
            saved=json.loads((p.root/'checkpoints/checkpoint-9/state.json').read_text())
            self.assertEqual(saved['best_validation'],p.state.kv['best_validation'])


if __name__=='__main__':unittest.main()
