"""Real CPU TensorDict/autograd checks; no simulated CUDA success claims."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from contextlib import nullcontext
import sys

import torch
from roll.distributed.scheduler.protocol import DataProto
from training.social_mixed.pipeline import make_batch, SocialPipeline
from training.social_mixed.workers import object_array, weighted_objective
from training.social_mixed.workers import SocialWorker
from training.social_mixed.run import configuration, validate_resume
from training.social_mixed.core import ROOT, load_data


def rows():
    return [dict(prompt_ids=[1,2,3],response_ids=[4,5],behavior_log_probs=[-.2,-.7],advantage=1.,loss_weight=.5),
            dict(prompt_ids=[1,2],response_ids=[6],behavior_log_probs=[-.4],advantage=-1.,loss_weight=1.5)]


class TrainingTests(unittest.TestCase):
    def test_exact_token_ids_masks_and_causal_shift(self):
        batch=make_batch(rows(),0)
        self.assertEqual(batch.batch['input_ids'].tolist(),[[1,2,3,4,5,0],[1,2,6,0,0,0]])
        self.assertEqual(batch.batch['response_mask'].tolist(),[[0,0,0,1,1,0],[0,0,1,0,0,0]])
        self.assertTrue(torch.allclose(batch.batch['behavior_log_probs'][0],torch.tensor([0,0,-.2,-.7,0])))
        self.assertEqual(batch.batch['advantages'].tolist(),[[0,0,1,1,0],[0,-1,0,0,0]])

    def test_real_protocol_object_arrays_survive_slice_chunk_concat(self):
        objects=[{'ids':[1,2]}, {'ids':[3]}, {'ids':[4,5,6]}]
        batch=DataProto.from_dict(tensors={'index':torch.arange(3)},non_tensors={'requests':object_array(objects)})
        selected=batch[[2,0]]
        chunks=selected.chunk(2)
        combined=DataProto.concat(chunks)
        self.assertEqual(combined.non_tensor_batch['requests'].tolist(),[objects[2],objects[0]])
        self.assertEqual(combined.non_tensor_batch['requests'].dtype,object)

    def test_gradient_direction_and_padding_invariance(self):
        logits=torch.tensor([[0.,0.],[0.,0.]],requires_grad=True)
        selected=logits.log_softmax(-1)[:,0:1]
        old=selected.detach().clone();adv=torch.tensor([[1.],[-1.]])
        loss,_,_=weighted_objective(selected,old,old,adv,torch.ones_like(adv),torch.ones(2),.2,.01)
        loss.backward()
        self.assertLess(logits.grad[0,0],0)
        self.assertGreater(logits.grad[1,0],0)
        padded=torch.cat([selected.detach(),torch.ones(2,3)],dim=1)
        mask=torch.tensor([[1.,0,0,0],[1.,0,0,0]])
        other,_,_=weighted_objective(padded,torch.cat([old,torch.ones(2,3)],1),padded,
                      torch.cat([adv,torch.zeros(2,3)],1),mask,torch.ones(2),.2,.01)
        self.assertAlmostEqual(loss.item(),other.item())

    def test_microbatch_accumulation_equals_full_weighted_objective(self):
        old=torch.tensor([[-.5,-.2],[-.3,-.7],[-.8,-.4]])
        adv=torch.tensor([[1.,1.],[-1.,-1.],[.5,.5]])
        weights=torch.tensor([.5,2.,.5]);mask=torch.ones_like(old)
        full=old.clone().requires_grad_()
        loss,_,_=weighted_objective(full,old,old,adv,mask,weights,.2,.01);loss.backward()
        micro=old.clone().requires_grad_()
        for i in range(3):
            value,_,_=weighted_objective(micro[i:i+1],old[i:i+1],old[i:i+1],adv[i:i+1],mask[i:i+1],weights[i:i+1],.2,.01)
            (value/3).backward()
        self.assertTrue(torch.allclose(full.grad,micro.grad))

    def test_both_configs_use_same_model_optimizer_and_limits(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,ROLL_OUTPUT_DIR=tmp,ROLL_LOG_DIR=tmp+'/logs',SOCIAL_MODEL='/model',PYTHONPATH=str(ROOT)):
            a,ra=configuration('mixed');b,rb=configuration('selfplay')
            ra.pop('exp_name');rb.pop('exp_name')
            self.assertEqual(ra,rb)
            self.assertEqual(a.actor_train.training_args.per_device_train_batch_size,2)
            self.assertEqual(a.actor_train.training_args.max_steps,1000)
            self.assertFalse(a.social_bp_curriculum) # no A100-specific NCCL preload gate

    def test_logprob_result_does_not_alias_megatron_scheduler_loss(self):
        worker=SocialWorker.__new__(SocialWorker)
        expected=torch.tensor([[1.,2.,3.]])
        worker.strategy=SimpleNamespace(op_compute_log_probs=lambda **kwargs:expected.clone())
        data=SimpleNamespace(batch={'input_ids':torch.ones(1,4,dtype=torch.long),
                                    'response_mask':torch.ones(1,4,dtype=torch.long)},meta_info={})
        scheduler_value,recorded=worker.forward_func_log_probs(data,torch.empty(0))
        scheduler_value.div_(3)
        torch.testing.assert_close(recorded['log_probs'],expected)


    def test_logprob_odd_padding_is_removed(self):
        batch=make_batch(rows()+rows()[:1],0)
        def compute(work,blocking):
            self.assertEqual(len(work),4)
            return DataProto.from_dict(tensors={'log_probs':torch.ones(4,5)})
        pipeline=SocialPipeline.__new__(SocialPipeline)
        with patch.object(DataProto,'materialize_concat',side_effect=lambda value:value):
            pipeline.log_probs(SimpleNamespace(compute_log_probs=compute),batch,'ref_log_probs')
        self.assertEqual(batch.batch['ref_log_probs'].shape,(3,5))

    def test_stop_handler_does_not_mutate_training_state(self):
        pipeline=SocialPipeline.__new__(SocialPipeline);pipeline.stop_requested=False
        pipeline.request_stop(10,None)
        self.assertTrue(pipeline.stop_requested)

    def test_native_worker_keeps_original_ids_logprobs_and_distinct_seeds(self):
        worker=SocialWorker.__new__(SocialWorker)
        worker.worker_config=SimpleNamespace(strategy_args=SimpleNamespace(strategy_name='vllm'))
        worker.tokenizer=SimpleNamespace(eos_token_id=9,decode=lambda ids,**kw:str(ids))
        def generate(prompts,sampling_params,use_tqdm):
            prompt_token_ids=[p["prompt_token_ids"] for p in prompts]
            self.assertEqual([p.seed for p in sampling_params],[42,43])
            self.assertTrue(all(p.temperature==1 and p.logprobs==0 for p in sampling_params))
            return [SimpleNamespace(prompt_token_ids=ids,outputs=[SimpleNamespace(token_ids=[5,9],finish_reason='stop',
                     logprobs=[{5:SimpleNamespace(logprob=-.4)},{9:SimpleNamespace(logprob=-.2)}])]) for ids in prompt_token_ids]
        worker.strategy=SimpleNamespace(model=SimpleNamespace(generate=generate))
        batch=DataProto.from_dict(tensors={'index':torch.arange(2)},non_tensors={'requests':object_array([
            dict(prompt_ids=[1,2],seed=42),dict(prompt_ids=[1,2],seed=43)])})
        fake=SimpleNamespace(SamplingParams=lambda **kw:SimpleNamespace(**kw))
        with patch.dict(sys.modules,vllm=fake),patch('training.social_mixed.workers.state_offload_manger',side_effect=lambda *a,**kw:nullcontext()):
            output=worker.generate_native(batch)
        records=output.non_tensor_batch['records'].tolist()
        self.assertEqual(records[0]['response_ids'],[5,9])
        self.assertEqual(records[0]['behavior_log_probs'],[-.4,-.2])

    def test_resume_rejects_wrong_arm_and_accepts_matching_manifest(self):
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);ckpt=root/'checkpoints/checkpoint-0';ckpt.mkdir(parents=True)
            (ckpt/'COMPLETE.json').write_text('{}')
            options=dict(arm='mixed',seed=42,tokens_per_update=65536)
            source=hashlib.sha256((ROOT/'examples/social_mixed/data_distribution_v1/manifest.json').read_bytes()).hexdigest()
            (root/'experiment.json').write_text(json.dumps(dict(options=options,model='/base',data_manifest_sha256=source)))
            validate_resume(ckpt,options,'/base')
            with self.assertRaises(ValueError):validate_resume(ckpt,dict(options,arm='selfplay'),'/base')

    def test_retention_only_removes_old_complete_checkpoints_and_staging(self):
        from training.social_mixed.checkpoints import prune
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for step in (0,9,19):
                for group in ('checkpoints','pipeline','actor_train-0','actor_train-1'):
                    path=root/group/f'checkpoint-{step}';path.mkdir(parents=True)
                    (path/'COMPLETE.json').write_text('{}')
            incomplete=root/'checkpoints/checkpoint-29';incomplete.mkdir()
            self.assertEqual(prune(root,2),[0])
            self.assertFalse((root/'actor_train-0/checkpoint-0').exists())
            self.assertTrue((root/'checkpoints/checkpoint-9/COMPLETE.json').exists())
            self.assertTrue(incomplete.exists())


if __name__=='__main__':unittest.main()
