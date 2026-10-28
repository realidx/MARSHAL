"""Execute the real CPU batch/reward/GRPO loss path before any Ray/model startup.

Definitions are loaded from production source with runtime-only imports omitted;
TensorDict, torch operations, DataProto and scheduler/loss bodies are unchanged.
Synthetic token sequences test contracts, not model quality or CUDA backend behavior.
"""
import ast
from collections import defaultdict
import copy
from dataclasses import dataclass, field
import enum
import json
import logging
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Dict, List, Optional, Union, Tuple, Callable, Any

import numpy as np
import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader
from torch.nn.utils.rnn import pad_sequence
from tensordict import TensorDict
import tensordict

from roll.utils.returns import compute_reinforce_return
from roll.utils.kl_controller import FixedKLController

ROOT = Path(__file__).resolve().parents[2]


def load_cpu_path():
    scope = dict(globals(), logger=logging.getLogger(__name__))
    class RuntimeImports(ast.NodeTransformer):
        def visit_ImportFrom(self, node):
            if node.module == 'roll.distributed.scheduler.protocol':
                return ast.copy_location(ast.Pass(), node)
            return node
    def execute(nodes, filename):
        module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), *nodes], type_ignores=[])
        module = ast.fix_missing_locations(RuntimeImports().visit(module))
        exec(compile(module, str(filename), 'exec'), scope)
    for name in ('roll/utils/functionals.py', 'roll/distributed/scheduler/protocol.py'):
        path = ROOT/name
        execute([n for n in ast.parse(path.read_text()).body if isinstance(n, (ast.FunctionDef, ast.ClassDef))], path)
    for name, cls_name, methods in (
        ('roll/distributed/scheduler/generate_scheduler.py', 'DynamicSamplingScheduler', ('expand_requests', 'postprocess_output_ids')),
        ('roll/distributed/strategy/strategy.py', 'InferenceStrategy', ('op_compute_log_probs', 'op_compute_entropy')),
        ('roll/pipeline/base_worker.py', 'ActorWorker', ('loss_func',)),
    ):
        path = ROOT/name; tree = ast.parse(path.read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls_name)
        execute([n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in methods], path)
        execute([n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'masked_ppo_clip_fractions'], path)
    return scope


def check_cpu_contract():
    scope = load_cpu_path(); proto = scope['DataProto']
    cfg = SimpleNamespace(social_bp_curriculum=True, sequence_length=20, generate_opt_level=1,
        is_num_return_sequences_expand=True, seed=20260915, max_len_mask=False, difficulty_mask=False,
        error_max_len_clip=False, adv_estimator='grpo', reward_shift=False, reward_clip=10.,
        actor_infer=SimpleNamespace(generating_args=SimpleNamespace(num_return_sequences=8)),
        kl_penalty='kl', add_token_level_kl=False, pg_clip=.2, pg_clip_high=.2,
        dual_clip_loss=False, loss_agg_mode='seq-mean-token-mean', use_kl_loss=True,
        kl_loss_coef=.01, entropy_loss_coef=0.)
    scheduler = SimpleNamespace(pipeline_config=cfg, generation_config={'num_return_sequences':8}, requests_buffers={})
    rows=[]
    for prompt in range(16):
        task=json.dumps(dict(id=f'contract-{prompt}', training_pack_version='bp-two-a100-v1'))
        request=proto.from_dict(tensors=dict(input_ids=torch.tensor([[0,1,2,3]]),
            attention_mask=torch.tensor([[0,1,1,1]]), position_ids=torch.tensor([[0,0,1,2]])),
            non_tensors=dict(ground_truth=np.array([task],dtype=object), domain=np.array(['social_bp'],dtype=object),
                             tag=np.array(['contract'],dtype=object)),
            meta_info=dict(global_step=0,generation_config={'num_return_sequences':8}))
        requests=scope['expand_requests'](scheduler,request)
        for sample, req in enumerate(requests):
            request_id=f'{prompt}-{sample}';scheduler.requests_buffers[request_id]=req
            tokens=[4,5,6] if sample%2==0 else [7]*16
            reason='stop' if sample%2==0 else 'length'
            output=scope['postprocess_output_ids'](scheduler,proto(meta_info=dict(request_id=request_id,
                eos_token_id=15,pad_token_id=0,output_token_ids=[tokens],output_finish_reasons=[reason])))
            score=float(prompt==1 or (prompt>1 and sample%2==0))
            scores=torch.tensor([score])
            output.union(proto.from_dict(tensors=dict(scores=scores,response_level_rewards=scores.clone(),
                token_level_rewards=torch.zeros_like(output.batch['responses'],dtype=torch.float32))))
            row=output[[0]]
            assert row.batch['input_ids'][row.batch['response_mask'].bool()].tolist()==tokens
            assert row.non_tensor_batch['bp_token_count'].tolist()==[len(tokens)]
            rows.append(row)
    batch=proto.concat(rows);batch.check_consistency()
    assert len(set(batch.non_tensor_batch['bp_sample_seed']))==128
    assert len(batch.group_by('domain')['social_bp'])==128
    assert len(batch.group_by('tag')['contract'])==128
    for chunk in batch.chunk(2):
        assert sum(len(item) for item in chunk.make_iterator(mini_batch_size=1,epochs=1))==64
    logits=torch.zeros(128,20,16,requires_grad=True)
    strategy=SimpleNamespace(
        op_compute_log_probs=lambda **kwargs:scope['op_compute_log_probs'](None,**kwargs),
        op_compute_entropy=lambda **kwargs:scope['op_compute_entropy'](None,**kwargs))
    old=strategy.op_compute_log_probs(logits=logits,input_ids=batch.batch['input_ids'],attention_mask=batch.batch['response_mask']).detach()
    batch.union(proto.from_dict(tensors=dict(old_log_probs=old,ref_log_probs=old.clone())))
    batch,_=scope['get_sample_level_mask'](batch,cfg)
    batch,_=scope['reward_postprocess'](batch,cfg,None)
    batch,_=scope['compute_token_reward'](batch,cfg,FixedKLController(0))
    batch=scope['compute_advantage'](batch,1.,1.,'grpo',response_mask=batch.batch['final_response_mask'])
    assert torch.count_nonzero(batch.batch['advantages'][:16])==0
    assert torch.count_nonzero(batch.batch['advantages'][16:])>0
    actor=SimpleNamespace(strategy=strategy,pipeline_config=cfg)
    loss,metrics=scope['loss_func'](actor,batch,logits)
    loss.backward()
    assert torch.isfinite(loss) and torch.isfinite(logits.grad).all() and torch.count_nonzero(logits.grad)>0
    assert torch.count_nonzero(logits.grad[:16])==0
    return dict(status='passed',samples=128,groups=16,group_size=8,independent_seeds=128,
                real_tensordict=True,real_batch_and_grpo_loss=True,finite_nonzero_gradient=True,
                cuda_or_deepspeed_test=False,torch_version=torch.__version__)


if __name__=='__main__':
    print(json.dumps(check_cpu_contract(),indent=2))
