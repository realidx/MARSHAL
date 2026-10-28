"""CPU integration checks; synthetic token evidence is not GPU/model validation."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from .terminal_training import StepRollout, Collector, group_advantages, score_response, mock_generate
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
            from .named_prompt import calls_for
            name,args=calls_for(job.tree.rules,job.node)[int(ai)]
            out['completion']['raw_message']['tool_calls'][0]['function']=dict(name=name,arguments=json.dumps(args))
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

    def test_group_normalization_preserves_wrong_action_value_order(self):
        # All actions are strictly wrong; binary labels would all be zero.
        rewards=[-2.,-2.,-2.,-2.,-2/3,-2/3,-2/3,-.5]
        a,mean,std=group_advantages(rewards)
        np.testing.assert_allclose(a,(np.array(rewards)-np.mean(rewards))/(np.std(rewards,ddof=1)+1e-8))
        self.assertLess(a[0],0);self.assertGreater(a[-1],0)
        shifted,_,_=group_advantages([r+9 for r in rewards]);np.testing.assert_allclose(a,shifted)
        for rewards in ([0.,0.],[-2.,-2.],[-2.,-2.+1e-8]):
            self.assertEqual(group_advantages(rewards)[0],[0.,0.])
        for bad in ([1.],[0.,float('nan')]):
            with self.assertRaises(ValueError):group_advantages(bad)

    def test_failure_uses_all_legal_values_and_does_not_advance(self):
        job=self.job(self.rows[0]);q,posterior=job.action_values();req,out=self.output(job)
        q=np.linspace(-3.,7.,len(q));out['finish_reason']='length'
        before=deepcopy(job.record())
        scored=score_response(job,out,req,q,posterior)
        self.assertEqual(scored['task_reward'],-10.)
        self.assertEqual(scored['binary_reward'],0)
        self.assertEqual(job.record(),before)
        out['finish_reason']='stop'
        from .named_prompt import calls_for
        name,args=calls_for(job.tree.rules,job.node)[len(q)-1]
        out['completion']['raw_message']['tool_calls'][0]['function']=dict(name=name,arguments=json.dumps(args))
        self.assertEqual(score_response(job,out,req,q,posterior)['task_reward'],0.)

    def test_collector_node_groups_weights_and_exact_resume(self):
        def mixed(requests):
            outs=mock_generate(requests)
            for req,out in zip(requests,outs):
                if req['seed']%5==0:out['finish_reason']='length'
            return outs
        collector=Collector(self.data,mixed,replicas=8,concurrency=32)
        rows,units,games,metrics=collector.collect(0,'slices',1)
        self.assertEqual(metrics['generated_tokens'],2*len(rows))
        self.assertEqual(len(rows),8*len(units))
        self.assertTrue(20<=len(units)<=22)
        self.assertEqual(metrics['root_decision_calls'],8*len(games))
        self.assertEqual(metrics['root_correct_calls'],sum(r['binary_reward'] for r in rows if r['decision_index']==0))
        for unit in units:
            calls=[r for r in rows if r['group']==unit['group']]
            self.assertEqual(len(calls),8)
            self.assertEqual(len({r['prompt_sha256'] for r in calls}),1)
            self.assertEqual(len({r['scoring_sha256'] for r in calls}),1)
            self.assertEqual(len({r['request']['seed'] for r in calls}),8)
            self.assertEqual(sum(r['selected_for_continuation'] for r in calls),1)
            self.assertAlmostEqual(sum(r['task_weight'] for r in calls)/len(rows),1/len(units))
            np.testing.assert_allclose([r['task_advantage'] for r in calls],group_advantages([r['task_reward'] for r in calls])[0])
            for r in calls:
                self.assertEqual((r['task_weight'],r['protocol_weight'],r['kl_weight']),(1.,1.,1.))
                self.assertEqual(r['protocol_advantage'],0. if r['valid'] else -.2)
                self.assertEqual(r['request']['max_tokens'],1024)
                text=r['request']['messages'][1]['content']
                self.assertIn(f'You will choose at most {r["remaining_k"]} more decision',text)
                self.assertNotIn('root_Q',text);self.assertNotIn('world_index',text)
        by_id={r['id']:r for r in self.rows}
        for game in games:
            chosen=[r for r in rows if r['chain']==game['chain'] and r['selected_for_continuation']]
            self.assertEqual(len(chosen),len(game['selected_nodes']))
            self.assertLessEqual(len(chosen),by_id[game['slice_id']]['k'])
            self.assertEqual([r['binary_reward'] for r in chosen],game['step_rewards'])
            audited=audit_game(self.tree,by_id[game['slice_id']],dict(game,calls=chosen),collector.cfg,{})
            for r,d in zip(chosen,audited['decisions']):
                self.assertEqual(r['oracle_step']['gap'],d['gap'])
                np.testing.assert_allclose(r['oracle_step']['Q'],d['Q'])
                np.testing.assert_allclose(r['oracle_step']['posterior'],d['posterior'])
        first=games[0];chosen=[r for r in rows if r['chain']==first['chain'] and r['selected_for_continuation']]
        tampered=deepcopy(dict(first,calls=chosen));tampered['calls'][0]['oracle_step']['Q'][0]+=1.
        with self.assertRaisesRegex(ValueError,'Training Q differs'):
            audit_game(self.tree,by_id[first['slice_id']],tampered,collector.cfg,{})
        restored=Collector(self.data,mixed,replicas=8,concurrency=32);restored.restore(collector.state)
        self.assertEqual(collector.collect(1,'slices',1),restored.collect(1,'slices',1))
        self.assertEqual(collector.state,restored.state)
        old=deepcopy(collector.state);old['version']='terminal-step-binary-shared-reset-loo-fixed-questions-v4'
        with self.assertRaisesRegex(ValueError,'contract changed'):restored.restore(old)

    def test_uniform_original_sample_is_score_independent_and_only_it_advances(self):
        from .common import seed_for
        row=next(r for r in self.rows if r['k']==3)
        data=SimpleNamespace(sha='one',train=[row],reference=self.data.reference)
        chosen=int(np.random.default_rng(seed_for(42,'terminal-train-advance',0,0)).integers(8))
        selected_seed=seed_for(42,'terminal-train-candidate',0,0,chosen)
        def fail_selected(requests):
            outs=mock_generate(requests)
            for req,out in zip(requests,outs):
                if req['seed']==selected_seed:out['finish_reason']='length'
            return outs
        rows,units,games,_=Collector(data,fail_selected,node_groups_per_update=1).collect(0,'slices')
        self.assertEqual((len(rows),len(units),len(games)),(8,1,1))
        self.assertEqual(units[0]['selected_replica'],chosen)
        self.assertEqual(games[0]['status'],'truncated');self.assertEqual(games[0]['controlled_decisions'],0)
        # Changing the oracle scores cannot change which original sample executes.
        original=score_response
        def altered(*args):
            r=original(*args);r['task_reward']=-1000. if r['request']['seed']==selected_seed else 0.;return r
        with patch('training.strategic_slices.terminal_training.score_response',side_effect=altered):
            _,different,other,_=Collector(data,fail_selected,node_groups_per_update=1).collect(0,'slices')
        self.assertEqual(different[0]['selected_replica'],chosen)
        self.assertEqual(games[0]['steps'],other[0]['steps']);self.assertEqual(games[0]['status'],other[0]['status'])
        # No candidate executes except selected; random choices do not consume
        # the reference RNG of seven discarded candidates.
        native_accept=StepRollout.accept;accepted=[]
        def witness(job,out,req):accepted.append(req['seed']);return native_accept(job,out,req)
        with patch.object(StepRollout,'accept',witness):
            rows,units,games,_=Collector(data,mock_generate,node_groups_per_update=1).collect(0,'slices')
        self.assertEqual(len(accepted),len(units))
        self.assertEqual(accepted,[r['request']['seed'] for r in rows if r['selected_for_continuation']])
        self.assertEqual(len(games),1)

    def test_infrastructure_and_missing_tokens_abort_without_cursor_commit(self):
        for generator in (lambda _: (_ for _ in ()).throw(RuntimeError('transport')),
                          lambda requests:[dict(completion={}) for _ in requests]):
            collector=Collector(self.data,generator,replicas=2,concurrency=2);before=deepcopy(collector.state)
            with self.assertRaises((RuntimeError,ValueError)):collector.collect(0,'slices',1)
            self.assertEqual(before,collector.state)
        batches=[]
        def fail_later(requests):
            batches.append(len(requests))
            if len(batches)>1:raise RuntimeError('later wave failed')
            return mock_generate(requests)
        collector=Collector(self.data,fail_later,concurrency=8);before=deepcopy(collector.state)
        with self.assertRaisesRegex(RuntimeError,'later wave'):collector.collect(0,'slices')
        self.assertEqual(collector.state,before)

    def test_discarded_failures_are_trained_but_do_not_terminate_selected_chain(self):
        from .common import seed_for
        def discarded_fail(requests):
            outs=mock_generate(requests)
            # One entrance at a time; infer its candidate node from its visible
            # remaining k, so all seven discarded responses can fail each node.
            for depth in range(3):
                chosen=int(np.random.default_rng(seed_for(42,'terminal-train-advance',0,depth)).integers(8))
                seeds={seed_for(42,'terminal-train-candidate',0,depth,r) for r in range(8) if r!=chosen}
                for req,out in zip(requests,outs):
                    if req['seed'] in seeds:out['completion']['raw_message']={}
            return outs
        rows,units,games,metrics=Collector(self.data,discarded_fail,node_groups_per_update=1).collect(0,'slices')
        self.assertEqual(len(games),1);self.assertEqual(games[0]['status'],'terminal')
        self.assertEqual(metrics['invalid_calls'],7*len(units))
        self.assertTrue(all(r['valid'] for r in rows if r['selected_for_continuation']))

    def test_all_failed_groups_keep_protocol_signal(self):
        for failure in ('length','invalid'):
            def fail(requests):
                outputs=mock_generate(requests)
                for out in outputs:
                    if failure=='length':out['finish_reason']='length'
                    else:out['completion']['raw_message']={}
                return outputs
            rows,_,games,metrics=Collector(self.data,fail,replicas=4,concurrency=4,node_groups_per_update=1).collect(0,'slices',1)
            self.assertTrue(all(r['binary_reward']==0 and r['task_advantage']==0 for r in rows))
            self.assertTrue(all(r['protocol_advantage']==-.2 and r['advantage']==-.2 for r in rows))
            self.assertTrue(all(g['utility'] is None for g in games))
            self.assertEqual(metrics['task_active_groups'],0)
            self.assertEqual(metrics['protocol_active_groups'],1)
            self.assertEqual(metrics['active_groups'],1)

    def test_fixed_node_budget_and_bounded_drain_across_concurrency(self):
        for concurrency in (3,8,32):
            a=Collector(self.data,mock_generate,replicas=8,concurrency=concurrency)
            low=a.collect(0,'slices',1)
            b=Collector(self.data,mock_generate,replicas=8,concurrency=concurrency)
            self.assertEqual(low,b.collect(0,'slices',10**9))
            rows,units,games,metrics=low
            self.assertTrue(20<=len(units)<=22)
            self.assertEqual(len(rows),8*len(units))
            self.assertEqual(a.state['cursor'],len(games))
            self.assertEqual(len(units),sum(len(g['selected_nodes']) for g in games))
            with self.assertRaisesRegex(ValueError,'node_groups_per_update'):
                Collector(self.data,mock_generate,node_groups_per_update=2,concurrency=concurrency).restore(a.state)

    def test_native_budget_and_settings(self):
        self.assertEqual(output_limit({}),1024)
        self.assertEqual(check_context(12288,{'max_tokens':4096},16384),4096)
        with self.assertRaisesRegex(ValueError,'refusing truncation'):check_context(12289,{'max_tokens':4096},16384)
        for bad in (True,0,-1,1.5):
            with self.assertRaises(ValueError):output_limit({'max_tokens':bad})
        from .train_terminal import settings
        cfg=SimpleNamespace(actor_infer=SimpleNamespace(generating_args=SimpleNamespace(),strategy_args=SimpleNamespace(strategy_config={})),
            actor_train=SimpleNamespace(training_args=SimpleNamespace()))
        settings(cfg,SimpleNamespace(context=16384,max_tokens=1024,concurrency=32,eval_every=10,save_every=30,max_steps=1000))
        self.assertEqual(cfg.prompt_length,15360);self.assertEqual(cfg.actor_infer.generating_args.max_new_tokens,1024)
        self.assertEqual(cfg.actor_infer.strategy_args.strategy_config,{'max_model_len':16384,'max_num_seqs':32})
        self.assertEqual((cfg.eval_steps,cfg.save_steps),(10,30))

    def test_production_loss_preserves_local_credit_and_response_mask(self):
        import math
        import torch
        from training.social_mixed.test_probability_diagnostic import function
        from training.social_mixed.objective import stable_objective
        class Proto:
            @staticmethod
            def from_dict(tensors):return SimpleNamespace(batch=tensors)
        make=function('pipeline.py','make_batch',dict(torch=torch,math=math,DataProto=Proto))
        flat=group_advantages([-2.,-.5])[0]+group_advantages([-1.,0.])[0]
        rows=[dict(prompt_ids=[1,2],response_ids=[3]*(i+1),behavior_log_probs=[-.5]*(i+1),
            advantage=a+(-.2 if i==0 else 0.),task_advantage=a,protocol_advantage=-.2 if i==0 else 0.,loss_weight=1.,
            task_weight=1.,protocol_weight=1.,kl_weight=1.,task_denominator=0.) for i,a in enumerate(flat)]
        data=make(rows,0).batch;mask=data['response_mask'][:,1:].float()
        old=data['behavior_log_probs'];logps=old.clone().requires_grad_()
        loss,_=stable_objective(logps,old,old+.1,mask,data,.2,.01);loss.backward()
        self.assertTrue(torch.all(logps.grad[~mask.bool()]==0))
        for i,a in enumerate(flat):
            protocol=-.2 if i==0 else 0.
            expected=(-(a+protocol)+.01*(1-math.exp(.1)))/(len(flat)*(i+1))
            torch.testing.assert_close(logps.grad[i][mask[i].bool()],torch.full((i+1,),expected))


if __name__=='__main__':unittest.main()
