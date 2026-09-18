"""CPU checks for prompt opt-in, baseline lifecycle, and best/last retention."""
import ast
from contextlib import nullcontext
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from training.social_mixed.checkpoints import prune,selection_score
from training.social_mixed.prompt_clarification import request,VERSION,clarify
from training.social_mixed.reasoning_requests import request as original
from training.social_mixed.prepare_reasoning_v5 import OUT,read
from training.social_mixed.core import Episode


class NextTrainingTests(unittest.TestCase):
    def test_bp_and_sp_same_small_clarification(self):
        t=read(OUT/'bp_train.jsonl')[0]
        updated=request(t);old=original(t)
        self.assertEqual(updated['tools'],old['tools'])
        self.assertEqual(updated['messages'][1]['content'],clarify(old['messages'][1]['content']))
        legacy=dict(t);legacy.pop('prompt_clarification')
        self.assertEqual(request(legacy),original(legacy))
        reset=read(OUT/'selfplay_train.jsonl')[0]
        self.assertIn('required commitments',Episode(reset,'g',0,42).request()['messages'][1]['content'])
        self.assertEqual(t['prompt_clarification'],VERSION)

    def test_prune_protects_best_and_latest(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            for n in (9,19,29):
                p=root/'checkpoints'/f'checkpoint-{n}';p.mkdir(parents=True);(p/'COMPLETE.json').write_text('{}')
            (root/'BEST_CHECKPOINT').write_text(str(root/'checkpoints/checkpoint-9'))
            self.assertEqual(prune(root,1),[19])
            self.assertTrue((root/'checkpoints/checkpoint-9').exists())
            (root/'BEST_CHECKPOINT').write_text(str(root/'checkpoints/checkpoint-29'))
            self.assertEqual(prune(root,1),[9])

    def test_selection_scores(self):
        m={f'bp/{k}/{mode}/accuracy':1 if k.startswith('B') else 0 for k in ('B1','B2','B3','P1','P2','P3','P4') for mode in ('binary','linear')}
        self.assertEqual(selection_score(m,'bp'),[.5])
        prefix='games/current_team/all/'
        m={prefix+'cohort_player_utility_lower':-.2,prefix+'completion_rate':.5,prefix+'invalid_rate':.1}
        self.assertEqual(selection_score(m,'selfplay'),[-.2,.5,-.1])

    def test_initial_validation_precedes_any_update_no_initial_save(self):
        # Execute the actual orchestration method with an empty update range;
        # distributed imports are intentionally not emulated as GPU success.
        source=Path(__file__).with_name('pipeline.py').read_text()
        cls=next(n for n in ast.parse(source).body if isinstance(n,ast.ClassDef) and n.name=='SocialPipeline')
        method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='run')
        method.decorator_list=[]
        namespace={'json':json}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[method],type_ignores=[])),'pipeline.run','exec'),namespace)
        events=[]
        with TemporaryDirectory() as tmp:
            fake=SimpleNamespace(root=Path(tmp),pipeline_config=SimpleNamespace(max_steps=0),state=SimpleNamespace(step=-1,kv={}),
                options={'total_tokens':10},stop_requested=False,phase=lambda _:nullcontext(),
                actor_train=SimpleNamespace(offload_states=lambda **_:events.append('offload')),
                model_update=lambda s:events.append(('sync',s)),validate=lambda s,t:events.append(('validation',s,t)),
                save=lambda *a,**kw:events.append('save'))
            namespace['run'](fake)
            self.assertEqual(events,['offload',('sync',0),('validation',-1,0)])
            self.assertFalse((Path(tmp)/'checkpoints').exists())


if __name__=='__main__':unittest.main()
