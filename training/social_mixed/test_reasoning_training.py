from copy import deepcopy
from unittest.mock import patch
import unittest

from training.social_mixed.reasoning_training import ReasoningCollector, group_advantages, WEIGHTS
from training.social_mixed.reasoning_validation import metrics_and_state, selection_score


def tasks():
    return [dict(id=f'{i}-{v}',canonical_id=str(i),package_id=str(i//2),split='train',paired_view=v,
        source_kernel='P'+str(i%4+1),completion_mode='binary',pool='test',kernel='B1' if v=='B' else 'P1',
        belief_action_relevant=i%3!=2)
        for i in range(12) for v in ('O','B','Pplus')]


class ReasoningTests(unittest.TestCase):
    def collector(self,length=1024,mixed=True):
        def generate(reqs):
            return [dict(request=r,response_ids=[1]*length,completion=dict(finish_reason='stop',value=int(mixed and j%2))) for j,r in enumerate(reqs)]
        return ReasoningCollector({'bp_train':tasks()},generate,concurrency=8)

    def run_batch(self,c,step,arm):
        with patch('training.social_mixed.paired_requests.request',side_effect=lambda *a,**k:{}),patch(
            'training.social_mixed.reasoning_scoring.score',side_effect=lambda t,c:dict(reward=c['value'],correct=bool(c['value']),status='ok')):
            return c.collect(step,arm)

    def test_default_normalization_and_sp_parallelism_restored(self):
        c=self.collector()
        self.assertEqual(c.normalization,'standard_sequence')
        self.assertEqual(getattr(c,'sp_replicas',4),4)
        self.assertEqual(c.sp_initial_groups,8)
        self.assertEqual(c.sp_initial_groups*c.sp_replicas,32)
        scores=[dict(status='ok',reward=v) for v in (0,1)]
        outputs=[dict(completion=dict(finish_reason='stop'))]*2
        advantages,_=group_advantages(scores,outputs,c.normalization)
        self.assertAlmostEqual(advantages[1],1.,places=5)

    def test_sp_schedule_continues_on_resume_and_covers_resets(self):
        from training.social_mixed.curriculum_sampling import reset_order
        import random
        resets=[dict(id=str(i),sampling_version='reasoning-v5',
                     raw=dict(game=dict(round_robin=[0]*slots)))
                for i,slots in enumerate((3,4,5,7,8,10,11))]
        c=self.collector()
        cycle_length=len(reset_order(resets,random.Random(0)))
        visited=[c.next_training_reset(resets)['id'] for _ in range(cycle_length)]
        self.assertEqual(set(visited),{r['id'] for r in resets})
        for _ in range(3):c.next_training_reset(resets)
        d=self.collector();d.restore(c.state)
        self.assertEqual([c.next_training_reset(resets) for _ in range(19)],
                         [d.next_training_reset(resets) for _ in range(19)])

    def test_static_monitor_only_uses_O_and_rejects_missing_answers(self):
        from training.social_mixed.reasoning_validation import ReasoningValidator
        validator=object.__new__(ReasoningValidator)
        validator.tasks=tasks();validator.seed=42;validator.concurrency=8
        validator.generate=lambda reqs:[dict(completion={'finish_reason':'stop'}) for _ in reqs]
        with patch('training.social_mixed.paired_requests.request',return_value={}), patch(
            'training.social_mixed.reasoning_scoring.score',return_value={'correct':True,'status':'ok'}), patch(
            'training.social_mixed.reasoning_scoring.decision_metrics',return_value={}):
            calls=validator.run_static_o()
            self.assertEqual(len(calls),12)
            self.assertEqual({r['task']['paired_view'] for r in calls},{'O'})
            self.assertTrue(all(r['request']['temperature']==0 for r in calls))
            validator.generate=lambda reqs:[]
            with self.assertRaises(RuntimeError):validator.run_static_o()

    def test_fixed_D_exposure_independent_of_lengths(self):
        c,d=self.collector(1024),self.collector(20)
        for step in range(3):
            cr,_,_,cm=self.run_batch(c,step,'decomposed');dr,_,_,dm=self.run_batch(d,step,'decomposed')
            self.assertEqual([(r['canonical_id'],r['request']['seed']) for r in cr],
                             [(r['canonical_id'],r['request']['seed']) for r in dr])
            self.assertEqual(len(cr),96)
            for view,w in WEIGHTS['decomposed'].items():
                self.assertEqual(cm[view+'/candidate_groups'],4)
                self.assertAlmostEqual(sum(r['task_weight'] for r in cr if r['kind']==view)/len(cr),w)

    def test_resume_schedule_and_zero_signal_do_not_resample(self):
        c=self.collector(mixed=False);rows,_,_,metrics=self.run_batch(c,0,'decomposed')
        self.assertEqual(metrics['candidate_groups'],12)
        self.assertEqual(metrics['B/semantic_contrast_groups'],0)
        self.assertTrue(all(r['task_advantage']==0 for r in rows))
        self.assertFalse(metrics['skip_optimizer']) # candidate KL/protocol still have a defined objective
        d=self.collector(mixed=False);d.restore(c.state)
        self.assertEqual(self.run_batch(c,1,'decomposed'),self.run_batch(d,1,'decomposed'))
        bad=deepcopy(d.state);bad['normalization']='centered_fixed'
        with self.assertRaises(ValueError):d.restore(bad)

    def test_paired_O_anchor_does_not_skip_full_coverage_cases(self):
        c=self.collector();visited=[]
        for step in range(12):
            rows,_,_,_=self.run_batch(c,step,'decomposed')
            visited.extend(r['canonical_id'] for r in rows if r['replica']==0 and r['kind']=='O')
        self.assertEqual(set(visited),set(c.schedule))

    def test_invalids_do_not_create_fake_semantic_contrast(self):
        scores=[dict(status='ok',reward=1)]*4+[dict(status='format_failure',reward=0)]*4
        outputs=[dict(completion=dict(finish_reason='stop'))]*8
        for norm in ('centered_fixed','standard_sequence'):
            adv,valid=group_advantages(scores,outputs,norm)
            self.assertEqual(adv,[0.]*8);self.assertEqual(sum(valid),4)
        scores[1]=dict(status='ok',reward=0)
        adv,_=group_advantages(scores,outputs,'centered_fixed')
        self.assertAlmostEqual(sum(adv),0.)

    def test_retention_and_selection_do_not_use_auxiliary_accuracy(self):
        def calls(ok):
            return [dict(task=dict(id=v,paired_view=v,package_id='p',canonical_id='c'),score=dict(correct=ok[v],status='ok')) for v in ('O','B','Pplus')]
        _,state=metrics_and_state(calls(dict(O=True,B=False,Pplus=True)))
        m,_=metrics_and_state(calls(dict(O=False,B=True,Pplus=True)),state)
        self.assertEqual(m['reasoning/O/forgotten_from_previous'],1)
        self.assertEqual(m['reasoning/B_Pplus_correct_O_wrong'],1)
        m['calbench/headline']=.2
        m['calbench/success_rate']=.25
        a=selection_score(m);m['reasoning/B/macro_accuracy']=100
        self.assertEqual(a,selection_score(m))


if __name__=='__main__':unittest.main()
