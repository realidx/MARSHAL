import ast
from pathlib import Path
import unittest
from unittest.mock import patch
import torch
from training.social_mixed.stabilization import StableCollector, learning_rate, VERSION

from training.social_mixed.objective import stable_objective as objective

class StableTests(unittest.TestCase):
    def test_cosine(self):
        self.assertAlmostEqual(learning_rate(0,100),1e-6)
        self.assertAlmostEqual(learning_rate(100,100),1e-7)
        self.assertAlmostEqual(learning_rate(200,100),1e-7)

    def test_formula_padding_microbatch_and_gradients(self):
        x=torch.zeros(2,4,requires_grad=True)
        mask=torch.tensor([[1.,1,0,0],[1.,1,1,1]])
        d=dict(task_advantage=torch.tensor([.5,-.5]),protocol_advantage=torch.zeros(2),
               task_weight=torch.ones(2),protocol_weight=torch.ones(2),kl_weight=torch.ones(2),
               task_denominator=torch.full((2,),1024.))
        loss,_=objective(x,x.detach(),x.detach(),mask,d,.2,.01)
        self.assertAlmostEqual(loss.item(),.5/1024)
        grad=torch.autograd.grad(loss,x)[0]
        self.assertAlmostEqual(abs(grad[0,0].item()),abs(grad[1,0].item()))
        for width in (4,7):
            z=torch.zeros(2,width,requires_grad=True)
            m=torch.nn.functional.pad(mask,(0,width-4))
            l,_=objective(z,z.detach(),z.detach(),m,d,.2,.01)
            self.assertAlmostEqual(l.item(),loss.item())
        parts=[]
        for i in range(2):
            z=torch.zeros(1,4,requires_grad=True)
            l,_=objective(z,z.detach(),z.detach(),mask[i:i+1],{k:v[i:i+1] for k,v in d.items()},.2,.01)
            parts.append(torch.autograd.grad(l/2,z)[0])
        self.assertTrue(torch.allclose(torch.cat(parts),grad))

    def tasks(self):
        return [dict(id=f'{d}{i}',task=d,pool='test',kernel=d+'1',completion_mode='binary')
                for d in ('B','P') for i in range(30)]

    def run_collector(self,mixed):
        def generate(reqs):
            return [dict(response_ids=[1,2],completion=dict(finish_reason='stop',value=int(mixed and i%2)))
                    for i,r in enumerate(reqs)]
        c=StableCollector({'bp_train':self.tasks()},generate,concurrency=8)
        with patch('training.social_mixed.b_bridge_requests.request',return_value={}),patch(
                'training.b_sft.social_bp_training.reward',side_effect=lambda t,c:dict(reward=c['value'],status='ok')):
            result=c.collect(0,'bp')
        return c,result

    def test_unique_effective_groups_and_resume(self):
        c,(rows,units,games,m)=self.run_collector(True)
        self.assertEqual(m['candidate_groups'],8)
        self.assertEqual(m['B/effective_groups'],4)
        self.assertEqual(len({r['task_id'] for r in rows}),8)
        self.assertEqual(m['generated_tokens'],128)
        for d in ('B','P'):
            self.assertAlmostEqual(sum(r['task_weight'] for r in rows if r['kind']==d)/len(rows),.5)
        other=StableCollector(c.data,c.generate,concurrency=8);other.restore(c.state)
        self.assertEqual(c.state,other.state)
        with self.assertRaises(ValueError):other.restore({'version':'old'})

    def test_zero_signal_bounded_skip(self):
        c,(rows,units,games,m)=self.run_collector(False)
        self.assertEqual(m['candidate_groups'],32)
        self.assertTrue(m['skip_optimizer'])
        self.assertTrue(all(r['task_weight']==0 for r in rows))

if __name__=='__main__':unittest.main()

class SPBaselineTests(unittest.TestCase):
    def test_incomplete_replica_does_not_clear_complete_player(self):
        from training.social_mixed.core import Collector
        reset=dict(id='r',raw=dict(game=dict(n_players=3,goals=[dict(binary=True)],round_robin=[0,1,2])))
        c=StableCollector({'selfplay_train':[reset]},lambda x:[],concurrency=4)
        c.state['baselines']={'3:binary:3':dict(mean=.5,count=16)}
        rows=[dict(unit=str(i),reset_id='r',loss_weight=1.,protocol_failure=None,task_advantage=0.,
                   protocol_advantage=0.) for i in range(3)]
        units=[dict(unit=str(i),utility=v) for i,v in enumerate([1.,None,0.])]
        with patch.object(Collector,'collect',return_value=(rows,units,[],{})):
            out,_,_,metrics=c.collect(0,'selfplay')
        self.assertEqual([r['task_advantage'] for r in out],[.5,0.,-.5])
        self.assertEqual(c.state['baselines']['3:binary:3']['count'],18)
        self.assertEqual(metrics['censored_player_episodes'],1)
        # Same frozen baseline within the update, including after earlier successes.
        self.assertTrue(all(r['baseline']==.5 for r in out))
