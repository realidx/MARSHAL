"""Exercise production batch/loss functions on CPU without Ray imports."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
import torch
from training.social_mixed.batching import trim,balanced_order
from training.social_mixed.probability_diagnostic import difference

ROOT=Path(__file__).resolve().parent

def function(file,name,namespace):
    tree=ast.parse((ROOT/file).read_text())
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
    exec(compile(ast.Module(body=[node],type_ignores=[]),file,'exec'),namespace)
    return namespace[name]

class ProbabilityTests(unittest.TestCase):
 def test_real_batch_shift_and_trim(self):
    class Proto:
        @staticmethod
        def from_dict(tensors):return SimpleNamespace(batch=tensors,meta_info={})
    import math
    make=function('pipeline.py','make_batch',dict(torch=torch,math=math,DataProto=Proto))
    rows=[dict(prompt_ids=[1,2,3],response_ids=[4,5],advantage=1,loss_weight=1,behavior_log_probs=[-.2,-.4]),dict(prompt_ids=[6],response_ids=[7],advantage=-1,loss_weight=1,behavior_log_probs=[-.8])]
    b=make(rows,0);trim(b)
    for i,r in enumerate(rows):
        mask=b.batch['response_mask'][i,1:].bool()
        self.assertEqual(b.batch['input_ids'][i,1:][mask].tolist(),r['response_ids'])
        torch.testing.assert_close(b.batch['behavior_log_probs'][i][mask],torch.tensor(r['behavior_log_probs']))
 def test_real_loss_equal_models_and_mask(self):
    loss=function('workers.py','weighted_objective',dict(torch=torch))
    x=torch.tensor([[-.2,-.5,-2.]],requires_grad=True);mask=torch.tensor([[1.,1.,0.]])
    value,pg,kl=loss(x,x.detach(),x.detach(),torch.ones_like(x),mask,torch.ones(1),.2,.01)
    self.assertAlmostEqual(value.item(),-1.);self.assertEqual(kl.item(),0.)
    value.backward();self.assertEqual(x.grad[0,2].item(),0.)
 def test_order_and_gross_difference(self):
    for replicas in [1,2]:
        lengths=[19,3,11,7];order=balanced_order(lengths,replicas)
        inverse=torch.argsort(torch.tensor(order)).tolist()
        received=[lengths[i] for i in order]
        self.assertEqual([received[i] for i in inverse],lengths)
    self.assertEqual(difference([[-1,-2]],[[-1,-2]])['maximum'],0)
if __name__=='__main__':unittest.main()
