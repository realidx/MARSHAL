import ast
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
import threading

import torch
import yaml

from training.b_sft.bp_two_gpu_data import ROOT, read, select_batch, sha
from training.b_sft.bp_training_probe import model_witness, tensor_digest
from training.b_sft.bp_two_gpu_preflight import validate_results, validate_versions, validate_deepspeed_api
from training.b_sft.bp_startup import prepare_roles


class StartupTests(unittest.TestCase):
    def run_roles(self,folder,fail=False):
        role=lambda name:SimpleNamespace(name=name,worker_cls='FakeWorker')
        cfg=SimpleNamespace(social_bp_curriculum=True,num_gpus_per_node=2,adv_estimator='grpo',output_dir=folder,
            actor_train=role('actor_train'),actor_infer=role('actor_infer'),reference=role('reference'),
            rewards={'social_bp':role('reward')})
        barrier=threading.Barrier(4,timeout=3);visited=[]
        def factory(**kwargs):
            visited.append(kwargs['name'])
            barrier.wait()  # Serial construction cannot pass this barrier.
            if fail and kwargs['name']=='reference':raise ValueError('failed import')
            return SimpleNamespace(name=kwargs['name'])
        return prepare_roles(cfg,object(),factory)

    def test_role_process_preparation_overlaps_and_keeps_roles_distinct(self):
        with TemporaryDirectory() as folder:
            roles=self.run_roles(folder)
            self.assertEqual(set(roles),{'actor_train','actor_infer','reference','reward:social_bp'})
            records=[r for p in Path(folder).glob('startup-*.jsonl') for r in read(p)]
            self.assertEqual(len(records),5)
            self.assertTrue(all(r['status']=='ok' for r in records))

    def test_preparation_failure_is_not_hidden(self):
        with TemporaryDirectory() as folder:
            with self.assertRaisesRegex(RuntimeError,'reference'):self.run_roles(folder,True)
            records=[r for p in Path(folder).glob('startup-*.jsonl') for r in read(p)]
            self.assertTrue(any(r['phase']=='create_reference' and r['status']=='failed' for r in records))


class EnvironmentTests(unittest.TestCase):
    def test_private_nccl_matches_completed_run_and_rejects_shared_cu12(self):
        from training.b_sft.prepare_b_grpo_nccl import EXPECTED, verify_loaded_library
        import base64
        manifest=json.loads((ROOT/'new/local_data/social_runs/b_grpo_b_r2_final/run_manifest.json').read_text())
        self.assertEqual(base64.urlsafe_b64encode(bytes.fromhex(manifest['nccl_sha256'])).decode().rstrip('='),EXPECTED)
        expected=manifest['ld_preload']
        with TemporaryDirectory() as folder:
            maps=Path(folder)/'maps'
            maps.write_text('100-200 r-xp 0 0 0 '+expected+'\n')
            self.assertEqual(verify_loaded_library(expected,maps),[expected])
            maps.write_text('100-200 r-xp 0 0 0 /site-packages/nvidia/nccl/lib/libnccl.so.2\n')
            with self.assertRaises(RuntimeError):verify_loaded_library(expected,maps)

    def test_private_nccl_is_forwarded_to_ray_driver_and_workers(self):
        config=yaml.safe_load((ROOT/'examples/social_bp/grpo_two_a100.yaml').read_text())
        self.assertEqual(config['system_envs']['LD_PRELOAD'],'${oc.env:LD_PRELOAD}')
        tree=ast.parse((ROOT/'training/b_sft/run_bp_two_gpu.py').read_text())
        keys={n.value for n in ast.walk(tree) if isinstance(n,ast.Constant) and isinstance(n.value,str)}
        self.assertTrue({'LD_PRELOAD','LD_LIBRARY_PATH','CUDA_HOME','NCCL_LIBRARY'}<=keys)

    def test_reviewed_deepspeed_versions_and_unreviewed_version(self):
        versions=dict(torch='2.6.0+cu118',vllm='0.8.5.post1+cu118',transformers='4.57.3')
        for version in ('0.16.3','0.16.4'):
            validate_versions(dict(versions,deepspeed=version))
        with self.assertRaises(RuntimeError):validate_versions(dict(versions,deepspeed='0.17.0'))

    def test_api_check_rejects_missing_or_incompatible_offload_interface(self):
        engine=SimpleNamespace(save_checkpoint=lambda self,path,tag=None:None,
            load_checkpoint=lambda self,path,tag=None:None,zero_offload_param=lambda self:None,
            zero_optimization_stage=lambda self:2,get_global_grad_norm=lambda self:0.)
        zero=SimpleNamespace(_update_model_bit16_weights=lambda self,index:None,
            _link_all_hp_params=lambda self:None,get_data_parallel_partitions=lambda self,tensor,group:None,
            state_dict=lambda self:{},load_state_dict=lambda self,state:None)
        enum=SimpleNamespace(**{name:name for name in ('lp_params','hp_params','lp_grads','contiguous_grad_buffer','optim_states')})
        self.assertEqual(len(validate_deepspeed_api(engine,zero,enum,lambda tensors:[])),10)
        zero.get_data_parallel_partitions=lambda self:None
        with self.assertRaises(TypeError):validate_deepspeed_api(engine,zero,enum,lambda tensors:[])
        del enum.hp_params
        zero.get_data_parallel_partitions=lambda self,tensor,group:None
        with self.assertRaises(RuntimeError):validate_deepspeed_api(engine,zero,enum,lambda tensors:[])


class FrozenDataTests(unittest.TestCase):
    def test_freeze_and_training_schedule(self):
        folder=ROOT/'examples/social_bp/data_two_a100_v1'
        tasks=read(folder/'tasks.jsonl')
        manifest=json.loads((folder/'manifest.json').read_text())
        for name,digest in manifest['files_sha256'].items():
            self.assertEqual(sha(folder/name),digest)
        self.assertEqual(Counter(t['split'] for t in tasks),dict(train=280,validation=67,test=64))
        old=read(ROOT/'examples/social_bp/data/tasks.jsonl')
        self.assertEqual([t['id'] for t in tasks if t['split']=='test'],[t['id'] for t in old if t['split']=='test'])
        self.assertEqual([{k:v for k,v in t.items() if k not in ('training_source','training_pack_version')} for t in tasks if t['split']=='test'],[t for t in old if t['split']=='test'])
        train=[t for t in tasks if t['split']=='train']
        self.assertFalse(any(t['task']=='B' and t['direct_answer'] for t in train))
        schedule=json.loads((folder/'schedule_seed20260915.json').read_text())
        exposures=Counter()
        for s in range(30):
            batch=select_batch(train,s,30,16,20260915)
            self.assertEqual([t['id'] for t in batch],schedule[s]['ids'])
            self.assertEqual(len({t['id'] for t in batch}),16)
            self.assertEqual(Counter(t['task'] for t in batch),dict(B=8,P=8))
            self.assertEqual(Counter(t['training_source'] for t in batch),dict(l0=2,bridge=3,original=11))
            info=[t for t in batch if t['pool']=='information']
            self.assertEqual(Counter(t['information_positive'] for t in info),{True:1,False:1})
            exposures.update(t['id'] for t in batch if t['training_source']=='l0')
        self.assertEqual(sorted(exposures.values()),[20,20,20])
        with self.assertRaises(ValueError):select_batch(tasks,0,30,16,1)

    def test_request_seeds_are_distinct_and_restore_stably(self):
        tree=ast.parse((ROOT/'roll/distributed/scheduler/generate_scheduler.py').read_text())
        fn=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='expand_requests')
        scope={'DataProto':object,'copy':__import__('copy')}
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'<scheduler>','exec'),scope)
        actor=SimpleNamespace(pipeline_config=SimpleNamespace(generate_opt_level=1,is_num_return_sequences_expand=True,social_bp_curriculum=True,seed=42),generation_config={'num_return_sequences':8})
        data=SimpleNamespace(meta_info={'generation_config':{},'global_step':1},non_tensor_batch={'ground_truth':[json.dumps(dict(id='x',training_pack_version='bp-two-a100-v1'))]})
        a=scope['expand_requests'](actor,deepcopy(data));b=scope['expand_requests'](actor,deepcopy(data))
        self.assertEqual([r.meta_info for r in a],[r.meta_info for r in b])
        self.assertEqual(len({r.meta_info['bp_sample_seed'] for r in a}),8)
        data.meta_info['global_step']=2
        c=scope['expand_requests'](actor,data)
        self.assertNotEqual(a[0].meta_info['bp_sample_seed'],c[0].meta_info['bp_sample_seed'])
        a[0].meta_info['generation_config']['seed']=0
        self.assertNotEqual(a[1].meta_info['generation_config']['seed'],0)

    def test_config_inheritance_and_memory_modes(self):
        def load(name):
            value=yaml.safe_load((ROOT/'examples/social_bp'/f'{name.split("@")[0]}.yaml').read_text())
            defaults=value.pop('defaults',[]);result={}
            for parent in defaults:
                if isinstance(parent,str) and parent!='_self_':result=merge(result,load(parent))
            return merge(result,value)
        def merge(a,b):
            a=deepcopy(a)
            for k,v in b.items():a[k]=merge(a.get(k,{}),v) if isinstance(v,dict) else v
            return a
        cfg=load('grpo_two_a100_preflight')
        self.assertEqual(cfg['num_gpus_per_node'],2)
        self.assertEqual(cfg['max_steps'],2)
        self.assertEqual(cfg['response_length'],1024)
        train=cfg['actor_train']['training_args']
        self.assertEqual(train['per_device_train_batch_size']*train['gradient_accumulation_steps'],128)
        self.assertEqual(cfg['actor_train']['strategy_args']['strategy_name'],'megatron_train')
        self.assertEqual(cfg['actor_train']['strategy_args']['strategy_config']['tensor_model_parallel_size'],2)
        for role in ('actor_train','actor_infer','reference'):self.assertEqual(cfg[role]['device_mapping'],'[0,1]')
        self.assertFalse(cfg['actor_train']['keep_states_on_device'])
        self.assertTrue(cfg['actor_infer']['strategy_args']['strategy_config']['enable_sleep_mode'])
        self.assertFalse(cfg['actor_infer']['strategy_args']['strategy_config']['enforce_eager'])


class WitnessTests(unittest.TestCase):
    def test_offloaded_reference_restores_integer_and_string_devices(self):
        tree=ast.parse((ROOT/'roll/utils/offload_states.py').read_text())
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='load_hf_model')
        scope={'PreTrainedModel':object,'AutoModelForCausalLMWithValueHead':type('Unused',(),{})}
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'<offload>','exec'),scope)
        loaded=[]
        model=SimpleNamespace(hf_device_map={'a':0,'b':'cuda:1','c':torch.device('cuda:0')},
                              get_submodule=lambda name:SimpleNamespace(to=lambda device:loaded.append(device)))
        scope['load_hf_model'](model)
        self.assertEqual(loaded,['cuda:0','cuda:1',torch.device('cuda:0')])

    def test_loaded_tensor_mutation_and_nonfinite_detection(self):
        params={k:torch.ones(16,dtype=torch.bfloat16) for k in ('model.embed_tokens.weight','model.norm.weight','model.layers.0.mlp.down_proj.weight')}
        model=SimpleNamespace(named_parameters=lambda:params.items())
        first=model_witness(model)
        params['model.layers.0.mlp.down_proj.weight'][4]=2
        self.assertNotEqual(first,model_witness(model))
        with self.assertRaises(RuntimeError):tensor_digest(torch.tensor([float('nan')]))

    def fixture(self,root):
        def witness(step,phase):
            w={'hash':'updated' if step==2 else 'base'}
            return dict(step=step,phase=phase,actor=[dict(global_steps=step,weights=w,optimizer=step)]*2,inference=[dict(weights=w)]*2,reference=['frozen']*2)
        for name,steps in (('continuous',(0,1)),('resumed',(1,))):
            run=root/name;run.mkdir()
            (run/'DRIVER_COMPLETE.json').write_text('{}')
            (run/'checkpoints/checkpoint-1').mkdir(parents=True)
            (run/'checkpoints/checkpoint-1/COMPLETE.json').write_text('{}')
            records=[witness(s,'before_rollout') for s in steps]+[witness(2,'final')]
            (run/'bp_weight_witness.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in records))
            for s in steps:
                rows=[dict(task_id=f't{i//8}',sample_seed=s*1000+i) for i in range(128)]
                (run/f'bp_rollout_train_{s}.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
            (run/'bp_rollout_final_2.jsonl').write_text((json.dumps(dict(policy_optimizer_steps=2))+'\n')*16)

    def test_preflight_rejects_stale_sampler_and_broken_restore(self):
        for field in ('inference','actor'):
            with TemporaryDirectory() as folder:
                root=Path(folder);self.fixture(root)
                self.assertEqual(validate_results(root)['status'],'passed')
                path=root/'resumed/bp_weight_witness.jsonl'
                records=read(path)
                records[0][field][0]['weights']={'hash':'stale'}
                path.write_text(''.join(json.dumps(r)+'\n' for r in records))
                with self.assertRaises(RuntimeError):validate_results(root)


if __name__=='__main__':unittest.main()
