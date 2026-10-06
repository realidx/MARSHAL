"""CPU integration checks; synthetic token evidence is not GPU/model validation."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest

import numpy as np

from .terminal_training import StepRollout, Collector, binary_advantages, mock_generate
from .terminal_analysis import audit_game
from .terminal_candidates import sample_member_world
from .terminal_d import TerminalRollout
from training.social_mixed.native_limits import output_limit, check_context


class TrainingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from .test_terminal_d import TerminalDTests
        TerminalDTests.setUpClass()
        cls.tree,cls.rows=TerminalDTests.tree,TerminalDTests.rows
        cls.cfg=dict(TerminalDTests.cfg,temperature=1.)
        cls.data=SimpleNamespace(sha='fixture',train=cls.rows,reference=lambda _:(cls.tree,{}))

    def job(self,row,replica=0,reset=None):
        reset=reset or sample_member_world(row,np.random.default_rng(42))
        return StepRollout(self.tree,row,replica,42,reset)

    def output(self,job,ai=None):
        req=job.request(self.cfg);out=mock_generate([req])[0]
        if ai is not None:
            out['completion']['raw_message']['tool_calls'][0]['function']['arguments']=json.dumps(dict(action_index=int(ai)))
        return req,out

    def test_shared_reset_without_collapsing_visible_belief(self):
        row=next(r for r in self.rows if sum(w>0 for w in r['members'][0]['world_weights'])>1)
        worlds=np.flatnonzero(row['members'][0]['world_weights'])
        a=self.job(row,0,(0,int(worlds[0])));b=self.job(row,1,(0,int(worlds[0])))
        self.assertEqual((a.index,a.world_index,a.ego),(b.index,b.world_index,b.ego))
        self.assertNotEqual(a.seed,b.seed)
        qa,qb=a.request(self.cfg),b.request(self.cfg)
        self.assertEqual(qa['messages'],qb['messages'])
        other=self.job(row,0,(0,int(worlds[1])))
        self.assertEqual(qa,other.request(self.cfg))
        av,aw=a.action_values();bv,bw=other.action_values()
        np.testing.assert_array_equal(av,bv);np.testing.assert_array_equal(aw,bw)
        self.assertGreater(np.count_nonzero(aw),1)

    def test_each_root_action_and_ties(self):
        ties=False
        for row in self.rows:
            q,_=self.job(row).action_values()
            ties |= sum(q.max()-q<=1e-7)>1
            for ai in range(len(q)):
                job=self.job(row);req,out=self.output(job,ai);job.accept(out,req)
                self.assertEqual(job.step_rewards,[int(q.max()-q[ai]<=1e-7)])
        self.assertTrue(ties)

    def test_k_handoff_and_independent_audit(self):
        ks=set();handoff=False;early=False;identity=self.tree.reference_identity()[0]
        for row in self.rows:
            ks.add(row['k'])
            for replica in range(8):
                original=TerminalRollout(self.tree,row,replica,42)
                job=self.job(row,replica,(original.member_index,original.world_index))
                while job.status=='running':
                    req,out=self.output(job);job.accept(out,req)
                self.assertEqual(job.status,'terminal')
                self.assertLessEqual(job.controlled,row['k'])
                early |= job.controlled<row['k']
                count=0
                for step in job.steps:
                    count+=step['source']=='model'
                    if step['source']=='saved-reference' and step['actor']==row['ego']:
                        self.assertEqual(count,row['k']);handoff=True
                # Same offline scorer used to audit the real D evidence.
                report=audit_game(self.tree,row,job.record(),self.cfg,{})
                for detail,audited in zip(job.step_details,report['decisions']):
                    self.assertAlmostEqual(detail['gap'],audited['gap'])
                    np.testing.assert_allclose(detail['posterior'],audited['posterior'])
        self.assertEqual(ks,{1,2,3});self.assertTrue(handoff);self.assertTrue(early)
        self.assertEqual(self.tree.reference_identity()[0],identity)

    def test_correct_prefix_survives_later_failure(self):
        for row in self.rows:
            if row['k']<2:continue
            for replica in range(8):
                start=self.job(row,replica);q,_=start.action_values()
                for ai in np.flatnonzero(q.max()-q<=1e-7):
                    job=self.job(row,replica);req,out=self.output(job,ai);job.accept(out,req)
                    if job.status!='running':continue
                    for failure in ('length','invalid'):
                        failed=deepcopy(job);req,out=self.output(failed)
                        if failure=='length':
                            out['finish_reason']=out['completion']['finish_reason']='length'
                        else:out['completion']['raw_message']={}
                        failed.accept(out,req)
                        self.assertEqual(failed.step_rewards,[1,0]);self.assertIsNone(failed.utility)
                        self.assertEqual(failed.status,'truncated' if failure=='length' else 'invalid_action')
                    return
        self.fail('Fixture has no correct prefix with a second controlled decision')

    def test_baseline_local_credit_and_degenerate_groups(self):
        for reward in (0,1):
            a,b=binary_advantages([[reward],[reward,reward]])
            self.assertEqual(a,[[0.],[0.,0.]])
        a,b=binary_advantages([[1,0],[0,0],[1]])
        self.assertEqual(b,[.5,.75,.25]);self.assertEqual(a,[[.5,-.5],[-.75,-.75],[.75]])
        _,changed=binary_advantages([[0],[0,0],[1]])
        self.assertEqual(changed[0],b[0])
        with self.assertRaises(ValueError):binary_advantages([[1]])

    def test_collector_weights_shared_groups_failure_and_resume(self):
        def mixed(requests):
            outs=mock_generate(requests)
            outs[0]['finish_reason']=outs[0]['completion']['finish_reason']='length'
            return outs
        collector=Collector(self.data,mixed,replicas=4,concurrency=8)
        self.assertEqual(collector.cfg['max_tokens'],1024)
        rows,units,games,metrics=collector.collect(0,'slices',1)
        self.assertTrue(any(g['status']=='truncated' for g in games))
        self.assertTrue(any(g['status']=='terminal' for g in games))
        self.assertEqual(metrics['generated_tokens'],2*len(rows))
        for group in {g['group'] for g in games}:
            members=[g for g in games if g['group']==group]
            self.assertEqual(len({(g['member_index'],g['world_index']) for g in members}),1)
        for unit in units:
            calls=[r for r in rows if r['unit']==unit['unit']]
            self.assertAlmostEqual(sum(r['task_weight'] for r in calls)/len(rows),1/len(units))
            for r in calls:
                self.assertEqual(r['protocol_advantage'],0. if r['valid'] else -.2)
                self.assertAlmostEqual(r['advantage'],r['task_advantage']+r['protocol_advantage'])
                self.assertEqual(r['request']['max_tokens'],1024)
        restored=Collector(self.data,mixed,replicas=4,concurrency=8);restored.restore(collector.state)
        self.assertEqual(collector.collect(1,'slices',1),restored.collect(1,'slices',1))
        self.assertEqual(collector.state,restored.state)
        with self.assertRaisesRegex(ValueError,'contract changed'):
            Collector(self.data,mixed,replicas=8).restore(collector.state)

    def test_infrastructure_and_missing_tokens_abort_without_cursor_commit(self):
        for generator in (lambda _: (_ for _ in ()).throw(RuntimeError('transport')),
                          lambda requests:[dict(completion={}) for _ in requests]):
            collector=Collector(self.data,generator,replicas=2,concurrency=2);before=deepcopy(collector.state)
            with self.assertRaises((RuntimeError,ValueError)):collector.collect(0,'slices',1)
            self.assertEqual(before,collector.state)

    def test_all_failed_groups_keep_protocol_signal(self):
        for failure in ('length','invalid'):
            def fail(requests):
                outputs=mock_generate(requests)
                for out in outputs:
                    if failure=='length':out['finish_reason']='length'
                    else:out['completion']['raw_message']={}
                return outputs
            rows,_,games,metrics=Collector(self.data,fail,replicas=4,concurrency=4,questions_per_update=1).collect(0,'slices',1)
            self.assertTrue(all(r['binary_reward']==0 and r['task_advantage']==0 for r in rows))
            self.assertTrue(all(r['protocol_advantage']==-.2 and r['advantage']==-.2 for r in rows))
            self.assertTrue(all(g['utility'] is None for g in games))
            self.assertEqual(metrics['task_active_groups'],0)
            self.assertEqual(metrics['protocol_active_groups'],1)
            self.assertEqual(metrics['active_groups'],1)

    def test_fixed_question_batch_is_independent_of_tokens_and_concurrency(self):
        a=Collector(self.data,mock_generate,replicas=8,concurrency=32)
        b=Collector(self.data,mock_generate,replicas=8,concurrency=8)
        low=a.collect(0,'slices',1);high=b.collect(0,'slices',10**9)
        self.assertEqual(low,high)
        rows,units,games,metrics=low
        self.assertEqual(metrics['groups'],4)
        self.assertEqual(len(games),32)
        self.assertEqual(len({g['slice_id'] for g in games}),4)
        self.assertEqual(a.state['cursor'],4)
        with self.assertRaisesRegex(ValueError,'questions_per_update'):
            Collector(self.data,mock_generate,questions_per_update=2).restore(a.state)

    def test_native_budget_and_settings(self):
        self.assertEqual(output_limit({}),1024)
        self.assertEqual(check_context(12288,{'max_tokens':4096},16384),4096)
        with self.assertRaisesRegex(ValueError,'refusing truncation'):check_context(12289,{'max_tokens':4096},16384)
        for bad in (True,0,-1,1.5):
            with self.assertRaises(ValueError):output_limit({'max_tokens':bad})
        from .train_terminal import settings
        cfg=SimpleNamespace(actor_infer=SimpleNamespace(generating_args=SimpleNamespace(),strategy_args=SimpleNamespace(strategy_config={})),
            actor_train=SimpleNamespace(training_args=SimpleNamespace()))
        settings(cfg,SimpleNamespace(context=16384,max_tokens=1024,concurrency=32,eval_every=10,max_steps=1000))
        self.assertEqual(cfg.prompt_length,15360);self.assertEqual(cfg.actor_infer.generating_args.max_new_tokens,1024)
        self.assertEqual(cfg.actor_infer.strategy_args.strategy_config,{'max_model_len':16384,'max_num_seqs':32})

    def test_production_loss_preserves_local_credit_and_response_mask(self):
        import math
        import torch
        from training.social_mixed.test_probability_diagnostic import function
        from training.social_mixed.objective import stable_objective
        class Proto:
            @staticmethod
            def from_dict(tensors):return SimpleNamespace(batch=tensors)
        make=function('pipeline.py','make_batch',dict(torch=torch,math=math,DataProto=Proto))
        advantages,_=binary_advantages([[1,0],[1]])
        flat=[v for trajectory in advantages for v in trajectory]
        rows=[dict(prompt_ids=[1,2],response_ids=[3,4],behavior_log_probs=[-.5,-.5],
            advantage=a,task_advantage=a,protocol_advantage=0.,loss_weight=1.,
            task_weight=1.,protocol_weight=1.,kl_weight=1.,task_denominator=0.) for a in flat]
        data=make(rows,0).batch;mask=data['response_mask'][:,1:].float()
        old=data['behavior_log_probs'];logps=old.clone().requires_grad_()
        loss,_=stable_objective(logps,old,old,mask,data,.2,.01);loss.backward()
        self.assertTrue(torch.all(logps.grad[~mask.bool()]==0))
        for i,a in enumerate(flat):
            torch.testing.assert_close(logps.grad[i][mask[i].bool()],torch.full((2,),-a/6))


if __name__=='__main__':unittest.main()
