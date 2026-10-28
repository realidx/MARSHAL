"""Regression checks for shortcut reinforcement and the actual curriculum route."""
import ast
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
import tempfile

import numpy as np

from training.b_sft.social_b_training_data import (
    BUCKETS, describe, single_queries, select_batch, diagnostics, diagnostic_metrics)
from training.b_sft.social_b_evaluation import score_attempt, request
from training.b_sft.social_b_rl import reward
from training.b_sft.test_social_b_evaluation import task, completion


def rows():
    return [dict(id=f'{b}-{i}', family=f'family-{i%3}',
                 curriculum=dict(bucket=b, gold_size=i%3+1, gold_favored='undetermined'))
            for b in BUCKETS for i in range(9)]


class TrainingDataTests(unittest.TestCase):
    def test_easy_other_query_cannot_pay_for_wrong_target_after_projection(self):
        t=task('multi',[{'action':'PASS'}],['want','neutral'])
        q=dict(player=1,goal=1)
        t['input']['queries'].append(q)
        t['gold']['judgments'].append(dict(**q,possible_preferences=['want','neutral','avoid'],favored='undetermined'))
        t['category_queries']=[dict(category='formation',query=t['input']['queries'][0]),dict(category='uninformative',query=q)]
        before=deepcopy(t)
        projected=list(single_queries(t))
        self.assertEqual(t,before)
        self.assertEqual(len({p['id'] for p in projected}),2)
        c=completion(['want','neutral','avoid'])
        self.assertEqual(reward(projected[0],c)['reward'],0)
        self.assertEqual(projected[0]['category_queries'],[t['category_queries'][0]])
        self.assertEqual(projected[0]['input']['history'],t['input']['history'])
        self.assertEqual(projected[0]['input']['public_type_catalogues'],t['input']['public_type_catalogues'])
        self.assertNotIn('curriculum',json.dumps(request(projected[0])))
        with self.assertRaisesRegex(ValueError,'must not average'):
            reward(dict(t,training_unit='single_query'),c)

    def test_short_history_is_not_enough_to_be_core(self):
        t=task('short',[{'action':'PASS'}],['want','neutral'])
        self.assertEqual(describe(t)['bucket'],'behavior_short')
        t['gold']['judgments'][0].update(possible_preferences=['want','neutral','avoid'],favored='undetermined')
        self.assertEqual(describe(t)['bucket'],'control')
        t['gold']['judgments'][0]['favored']='want'
        self.assertEqual(describe(t)['bucket'],'behavior_short')
        t['input']['history']*=3
        self.assertEqual(describe(t)['bucket'],'behavior_long')

    def test_schedule_fades_core_difficulty_and_keeps_controls(self):
        data=rows(); counts=[]
        for step in range(60):
            batch=select_batch(data,step,60,4,9)
            self.assertEqual(batch,select_batch(data,step,60,4,9))
            self.assertEqual(len({r['id'] for r in batch}),4)
            c=Counter(r['curriculum']['bucket'] for r in batch)
            self.assertEqual(c['control'],1); counts.append(c)
        self.assertGreater(sum(c['behavior_short'] for c in counts[:20]),sum(c['behavior_short'] for c in counts[-20:]))
        with self.assertRaisesRegex(ValueError,'coverage'):
            select_batch([r for r in data if r['curriculum']['bucket']!='behavior_short'],0,60,4,9)

    def test_validation_detects_fullset_shortcut_and_counts_failures(self):
        t=task('a',[{'action':'PASS'}],['want','neutral']);t['curriculum']=describe(t)
        a=diagnostics(t,score_attempt(t,completion(['want','neutral','avoid'])))
        b=diagnostics(t,score_attempt(t,dict(message=dict(content='bad'))))
        self.assertEqual(set(a),set(b))
        tensors={'b_'+k:np.array([a[k],b[k]],dtype=float) for k in a}
        m=diagnostic_metrics(tensors)
        self.assertEqual(m['val_b/wrong_full_when_exclusion_needed'],.5)
        self.assertEqual(m['val_b/behavior_short_exact'],0)
        self.assertEqual(m['val_b/valid'],.5)

    def test_real_scheduler_uses_curriculum_only_for_training(self):
        # Execute the real get_batch up to its existing request loop. The loop is
        # intercepted after selection, before any GPU/Ray work is requested.
        tree=ast.parse(Path('roll/distributed/scheduler/generate_scheduler.py').read_text())
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='DynamicSamplingScheduler')
        fn=deepcopy(next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='get_batch'))
        for arg in fn.args.args: arg.annotation=None
        fn.returns=None
        loop=next(i for i,n in enumerate(fn.body) if isinstance(n,ast.While))
        fn.body=fn.body[:loop]+[ast.parse('return curriculum_indices').body[0]]
        scope={'copy':__import__('copy'),'itertools':__import__('itertools')}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'scheduler','exec'),scope)
        teachers=[dict(r,training_unit='single_query',input=dict(queries=[dict(player=1,goal=0)])) for r in rows()]
        scheduler=SimpleNamespace(pipeline_config=SimpleNamespace(social_b_curriculum=True,max_steps=60,seed=9),
            is_use_additional_prompts=False,dataset={'ground_truth':[json.dumps(r) for r in teachers]},reset_status=lambda:None)
        data=SimpleNamespace(meta_info=dict(global_step=0,generation_config=dict(num_return_sequences=8)))
        actual=list(scope['get_batch'](scheduler,data,4))
        expected=[teachers.index(r) for r in select_batch(teachers,0,60,4,9)]
        self.assertEqual(actual,expected)
        data.meta_info['evaluation_phase']='periodic'
        self.assertIsNone(scope['get_batch'](scheduler,data,4))

    def test_export_guard_rejects_changed_data_and_cross_split_families(self):
        from training.b_sft.social_b_grpo import validate_export
        from training.b_sft.social_b_rl import digest
        from training.b_sft.social_b_training_data import VERSION
        with tempfile.TemporaryDirectory() as root:
            folder=Path(root)
            def write(cross_family=False):
                for split in ('train','validation','test'):
                    ts=[dict(r,family=r['family'] if cross_family else split+r['family'],training_unit='single_query',
                             input=dict(queries=[dict(player=1,goal=0)]),gold=dict(judgments=[{}])) for r in rows()]
                    (folder/(split+'.jsonl')).write_text(''.join(json.dumps(dict(id=t['id'],ground_truth=json.dumps(t)))+'\n' for t in ts))
                manifest=dict(training_unit='single_query',curriculum_version=VERSION,
                    files_sha256={s+'.jsonl':digest(folder/(s+'.jsonl')) for s in ('train','validation','test')})
                (folder/'manifest.json').write_text(json.dumps(manifest))
            write();validate_export(folder)
            with (folder/'train.jsonl').open('a') as f:f.write('\n')
            with self.assertRaisesRegex(ValueError,'changed'):validate_export(folder)
            write(cross_family=True)
            with self.assertRaisesRegex(ValueError,'Family leakage'):validate_export(folder)


if __name__=='__main__': unittest.main()
