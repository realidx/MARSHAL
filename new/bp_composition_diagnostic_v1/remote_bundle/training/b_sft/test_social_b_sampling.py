"""Exercise the real dynamic scheduler's request expansion without Ray actors."""
from types import SimpleNamespace
import unittest
import torch
from roll.distributed.scheduler.generate_scheduler import DynamicSamplingScheduler
from roll.distributed.scheduler.protocol import DataProto


def check_sampling_config(config):
    if config.generate_opt_level != 1:
        raise ValueError('B RLVR uses DynamicSamplingScheduler and requires generate_opt_level=1')
    if config.is_num_return_sequences_expand:
        raise ValueError('B GRPO keeps each prompt group in one request')
    expand=DynamicSamplingScheduler.__ray_metadata__.modified_class.expand_requests
    for name, args, expected in (
        ('train',config.actor_infer.generating_args,config.num_return_sequences_in_group),
        ('validation',config.validation.generating_args,1),
    ):
        generation=args.to_dict()
        assert generation['num_return_sequences']==expected
        scheduler=SimpleNamespace(pipeline_config=config,generation_config=generation)
        data=DataProto.from_dict(tensors={'input_ids':torch.tensor([[11,22,33]])},
                                meta_info={'generation_config':dict(generation)})
        requests=expand(scheduler,data)
        assert len(requests)==1, name
        assert requests[0].meta_info['generation_config']['num_return_sequences']==expected,name
        assert torch.equal(requests[0].batch['input_ids'],data.batch['input_ids']),name
        print(f'{name}: dynamic request expansion passed, {expected} completions per prompt')


class SamplingTests(unittest.TestCase):
    def config(self,level):
        def args(n):return SimpleNamespace(to_dict=lambda:dict(num_return_sequences=n))
        return SimpleNamespace(generate_opt_level=level,is_num_return_sequences_expand=False,
            actor_infer=SimpleNamespace(generating_args=args(8)),
            validation=SimpleNamespace(generating_args=args(1)),num_return_sequences_in_group=8)

    def test_train_and_validation_request_expansion(self):
        check_sampling_config(self.config(1))

    def test_unsupported_batch_mode_fails_before_actor_start(self):
        with self.assertRaisesRegex(ValueError,'DynamicSamplingScheduler'):
            check_sampling_config(self.config(0))


if __name__=='__main__': unittest.main()
