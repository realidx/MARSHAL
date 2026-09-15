"""Real scheduler construction on CPU; no model loading or distributed init."""
import unittest
import torch
from roll.configs.training_args import TrainingArguments
from roll.distributed.strategy.deepspeed_strategy import create_train_scheduler


class SchedulerTests(unittest.TestCase):
    def curve(self, name):
        args=TrainingArguments(lr_scheduler_type=name, warmup_steps=2)
        optimizer=torch.optim.SGD([torch.nn.Parameter(torch.zeros(1))],lr=1.0)
        scheduler=create_train_scheduler(args,optimizer,10)
        rates=[scheduler.get_last_lr()[0]]
        for _ in range(10):
            optimizer.step()
            scheduler.step()
            rates.append(scheduler.get_last_lr()[0])
        return rates

    def test_linear_warmup_and_decay(self):
        self.assertEqual(self.curve('linear'),[0.,.5,1.,.875,.75,.625,.5,.375,.25,.125,0.])

    def test_cosine_with_and_without_min_lr(self):
        for name in ('cosine','cosine_with_min_lr'):
            rates=self.curve(name)
            self.assertEqual(rates[:3],[0.,.5,1.])
            self.assertAlmostEqual(rates[-1],0.)


if __name__ == '__main__':
    unittest.main()
