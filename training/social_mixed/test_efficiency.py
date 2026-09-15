"""CPU tests for batching math, semantic preservation and group refilling."""
import unittest
from types import SimpleNamespace as NS
from collections import Counter
import torch
from training.social_mixed.batching import trim,pad_weights,balanced_order
from training.social_mixed.hardware import PROFILES,apply
from training.social_mixed.core import Collector,load_data
from training.social_mixed.test_core import generated

class EfficiencyTests(unittest.TestCase):
 def test_padding_preserves_weighted_gradient_for_all_profiles(self):
  for micro in (1,2,4):
   for n in (1,3,7,8):
    w=torch.arange(1,n+1,dtype=torch.float64);w=w/w.mean()
    x=torch.tensor(.4,requires_grad=True,dtype=torch.float64)
    losses=(x-torch.arange(n,dtype=torch.float64)).square();(losses*w).mean().backward();expected=x.grad.clone()
    x.grad=None;padded=((n+micro-1)//micro)*micro
    indices=list(range(n))+[n-1]*(padded-n);weights=pad_weights(w,padded)
    for i in range(0,padded,micro):
     loss=(x-torch.tensor(indices[i:i+micro],dtype=torch.float64)).square()
     ((loss*weights[i:i+micro]).mean()/(padded//micro)).backward()
    torch.testing.assert_close(x.grad,expected)
 def test_trim_preserves_tokens_masks_and_shifted_targets(self):
  ids=torch.tensor([[1,2,3,0,0,0,0,0],[4,5,6,7,8,0,0,0]])
  targets=torch.arange(14).reshape(2,7)
  d=NS(batch=dict(input_ids=ids,attention_mask=(ids!=0).long(),response_mask=(ids!=0).long(),position_ids=torch.arange(8).expand(2,8),advantages=targets,loss_weight=torch.ones(2)),meta_info={})
  trim(d)
  self.assertEqual(d.batch['input_ids'].shape,(2,6));self.assertEqual(d.meta_info['social_original_width'],8)
  torch.testing.assert_close(d.batch['advantages'],targets[:,:5]);torch.testing.assert_close(d.batch['input_ids'],ids[:,:6])
  self.assertEqual(d.batch['loss_weight'].shape,(2,))
 def test_balanced_order_restores_outputs_and_avoids_long_half(self):
  lengths=[100,101,200,201,1000,1001]
  order=balanced_order(lengths)
  self.assertEqual(set(order),set(range(6)))
  totals=[sum(lengths[i] for i in order[:3]),sum(lengths[i] for i in order[3:])]
  self.assertEqual(abs(totals[0]-totals[1]),3)
  result=torch.tensor(order)[torch.argsort(torch.tensor(order))]
  self.assertEqual(result.tolist(),list(range(6)))
 def test_profiles_keep_objective_independent(self):
  for name,p in PROFILES.items():
   c=NS(actor_train=NS(training_args=NS(),strategy_args=NS(strategy_config=NS())),reference=NS(),actor_infer=NS(strategy_args=NS(strategy_config=NS())))
   apply(c,name);self.assertEqual(c.actor_train.training_args.per_device_train_batch_size,p['train_microbatch'])
   self.assertEqual(c.actor_infer.strategy_args.strategy_config.max_num_seqs,p['max_num_seqs'])
 def test_refill_completes_every_admitted_replica_and_stops(self):
  def fake(reqs):
   outputs=[]
   for req in reqs:
    names=[t['function']['name'] for t in req['tools']]
    outputs.append(generated('PASS' if 'PASS' in names else 'REJECT',{}))
   return outputs
  rows,units,games,m=Collector(load_data(),fake,concurrency=8).collect(0,'selfplay',token_target=180)
  self.assertGreater(m['admitted_reset_groups'],2)
  self.assertEqual(len(games),4*m['admitted_reset_groups'])
  self.assertTrue(all(g['status']=='terminal' for g in games))
  self.assertLessEqual(m['peak_active_games'],8)
  self.assertGreaterEqual(m['generated_tokens'],180)
  groups=Counter(u['group'] for u in units)
  self.assertTrue(all(n==4 for n in groups.values()))
if __name__=='__main__':unittest.main()
