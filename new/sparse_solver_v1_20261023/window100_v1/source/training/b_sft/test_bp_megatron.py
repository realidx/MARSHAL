"""CPU regressions for the B/P Megatron migration; no CUDA kernels are exercised."""
import ast
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import List, Tuple
from unittest.mock import patch

import pytest
import torch

from training.b_sft.bp_cpu_preflight import load_cpu_path
from training.b_sft.bp_megatron import complete_checkpoint, optimizer_witness
from training.b_sft.bp_training_probe import optimizer_step_count
from training.b_sft.run_bp_two_gpu import config

ROOT = Path(__file__).resolve().parents[2]


def composed(name='grpo_two_a100'):
    env={key:'/private/tmp/bp-test' for key in ('BP_RUN_DIR','BP_EXPORT_DIR','BP_MODEL',
        'PYTHONPATH','LD_LIBRARY_PATH','LD_PRELOAD','NCCL_LIBRARY')}
    with patch.dict(os.environ,env):
        return config(name)[0]


def test_real_config_composition_and_optimizer_horizon():
    for name, steps in (('grpo_two_a100',30),('grpo_two_a100_preflight',2)):
        cfg=composed(name);args=cfg.actor_train.training_args
        assert args.max_steps==steps
        assert args.bf16 and args.optimizer_backend=='megatron'
        assert args.gradient_accumulation_steps==128
        assert args.lr_scheduler_kwargs=={'lr_decay_steps':30}
        assert args.warmup_steps==5
        assert cfg.checkpoint_config['verify_megatron_checkpoint']
        assert not cfg.checkpoint_config['verify_deepspeed_checkpoint']
        assert cfg.actor_train.strategy_args.strategy_config['sequence_parallel']
        assert cfg.sequence_length==3072
        assert cfg.expected_actor_optimizer_steps_per_rollout==1


def test_formal_deepspeed_entry_keeps_frozen_experiment_and_avoids_megatron():
    cfg=composed('grpo_two_a100_deepspeed')
    actor=cfg.actor_train
    assert actor.strategy_args.strategy_name=='deepspeed_train'
    assert actor.strategy_args.strategy_config['zero_optimization']['stage']==2
    assert not actor.strategy_args.strategy_config['zero_optimization']['overlap_comm']
    assert actor.strategy_args.strategy_config['zero_optimization']['reduce_bucket_size']==10000000
    assert actor.training_args.optimizer_backend=='torch_adamw_fused'
    assert actor.training_args.gradient_accumulation_steps==64
    assert actor.training_args.max_steps//2==cfg.max_steps==30
    assert cfg.rollout_batch_size*cfg.num_return_sequences_in_group==128
    assert cfg.eval_steps==cfg.save_steps==10 and cfg.val_batch_size==67
    assert cfg.validation.generating_args.num_return_sequences==4
    # BaseConfig consumes the deprecated response_length into sequence_length.
    assert cfg.sequence_length==3072 and not cfg.bp_two_gpu_preflight
    assert cfg.actor_infer.generating_args.max_new_tokens==1024
    assert cfg.validation.generating_args.max_new_tokens==1024
    assert cfg.checkpoint_config['verify_deepspeed_checkpoint']
    assert not cfg.checkpoint_config.get('verify_megatron_checkpoint',False)
    assert cfg.system_envs['BP_STARTUP_DIAGNOSTICS']=='1'


def test_mca_receives_final_arguments_without_roll_only_backend():
    cfg=composed();received={}
    cls=next(n for n in ast.parse((ROOT/'roll/distributed/strategy/megatron_strategy.py').read_text()).body
             if isinstance(n,ast.ClassDef) and n.name=='MegatronInferStrategy')
    init=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='__init__')
    # Execute the production constructor, replacing the GPU parent and MCA factory.
    class Base:
        def __init__(self,worker):self.worker=worker;self.worker_config=worker.worker_config
    def factory(**kwargs):received.update(kwargs);return SimpleNamespace(**kwargs)
    node=ast.ClassDef(name=cls.name,bases=[ast.Name(id='Base',ctx=ast.Load())],
        keywords=[],body=[init],decorator_list=[])
    scope=dict(Base=Base,Worker=object,TrainingArguments=factory,logger=SimpleNamespace(info=lambda _:None))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<constructor>','exec'),scope)
    scope[cls.name](SimpleNamespace(worker_config=cfg.actor_train,pipeline_config=cfg))
    assert 'optimizer_backend' not in received
    assert received['tensor_model_parallel_size']==2
    assert received['seed']==cfg.seed
    assert received['bf16'] and received['gradient_accumulation_steps']==128


def test_tp_dispatch_preserves_full_128_answer_batch():
    scope=load_cpu_path();proto=scope['DataProto']
    source=ast.parse((ROOT/'roll/distributed/scheduler/decorator.py').read_text())
    nodes=[n for n in source.body if isinstance(n,ast.FunctionDef)
           and n.name in ('_split_args_kwargs','_dispatch_dp_mp_compute')]
    scope.update(Tuple=Tuple,List=List)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'<dispatch>','exec'),scope)
    ranks=[SimpleNamespace(dp_rank=0,tp_rank=r,cp_rank=0,pp_rank=0) for r in (0,1)]
    cluster=SimpleNamespace(dp_size=1,world_size=2,get_rank_info=lambda rank:ranks[rank])
    batch=proto.from_dict(tensors={'input_ids':torch.arange(128).reshape(128,1)},
                          meta_info={'global_step':0})
    args,_=scope['_dispatch_dp_mp_compute'](cluster,False,batch)
    assert all(len(b)==128 for b in args[0])
    args,_=scope['_dispatch_dp_mp_compute'](cluster,True,batch)
    assert len(args[0][0])==128 and args[0][1].batch is None
    assert args[0][1].meta_info==batch.meta_info
    # TP rank one receives tensors through Megatron's existing broadcast.


def test_backend_counter_and_master_adam_witness_detect_changes():
    strategy=SimpleNamespace(strategy_name='megatron_train',scheduler=SimpleNamespace(num_steps=2))
    assert optimizer_step_count(strategy)==2
    strategy.scheduler.num_steps=None
    with pytest.raises(RuntimeError):optimizer_step_count(strategy)
    master=torch.ones(4);adam=torch.ones(4)
    optimizer=SimpleNamespace(shard_fp32_from_float16_groups=[[master]],
        optimizer=SimpleNamespace(state_dict=lambda:{'state':{0:{'exp_avg':adam}}}))
    first=optimizer_witness(optimizer);master[0]=2
    assert first['master']!=optimizer_witness(optimizer)['master']
    adam[0]=3
    assert first['adam']!=optimizer_witness(optimizer)['adam']


def checkpoint_fixture(root):
    for name in ('mca_config.json','tokenizer.json','tokenizer_config.json',
                 'pipeline/worker_state_pipeline.json','iter_0000001/dist_optimizer/metadata.json'):
        p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('{}')
    for name in ('scheduler.pt','pipeline/rng_state_pipeline.pth',
                 'rng_state/rng_state_0.pth','rng_state/rng_state_1.pth',
                 'iter_0000001/mp_rank_00/model_optim_rng.pt','iter_0000001/mp_rank_01/model_optim_rng.pt',
                 'iter_0000001/dist_optimizer/common.pt'):
        p=root/name;p.parent.mkdir(parents=True,exist_ok=True);torch.save({'value':torch.ones(2)},p)
    (root/'latest_checkpointed_iteration.txt').write_text('1')
    for name in ('.metadata','__0_0.distcp','__1_0.distcp'):
        (root/'iter_0000001/dist_optimizer'/name).write_bytes(b'fixture')


def test_checkpoint_requires_both_tp_models_optimizer_and_rng():
    with TemporaryDirectory() as folder:
        root=Path(folder);checkpoint_fixture(root)
        result=complete_checkpoint(root,2,1)
        assert result['backend']=='megatron_train'
        assert json.loads((root/'COMPLETE.json').read_text())['tp']==2
        path=root/'rng_state/rng_state_1.pth';path.unlink()
        with pytest.raises(RuntimeError,match='Incomplete checkpoint'):complete_checkpoint(root,2,1)
        assert not (root/'COMPLETE.json').exists()
        checkpoint_fixture(root)
        (root/'iter_0000001/mp_rank_01/model_optim_rng.pt').unlink()
        with pytest.raises(RuntimeError,match='Incomplete checkpoint'):complete_checkpoint(root,2,1)
