"""Export, run two updates, restore checkpoint after update one, and verify evidence."""
import argparse
import importlib.metadata
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys


def read(path):
    return [json.loads(s) for s in Path(path).read_text().splitlines() if s.strip()]


def validate_versions(versions, backend='deepspeed'):
    supported={'torch':{'2.6.0'},'vllm':{'0.8.5.post1'},'transformers':{'4.51.3','4.57.3'},
               'deepspeed':{'0.16.3','0.16.4'}}
    for name,allowed in supported.items():
        if name=='deepspeed' and backend=='megatron':continue
        if versions[name].split('+')[0] not in allowed:
            raise RuntimeError(f'Unverified training API version {name}={versions[name]}; inspect before running')


def validate_deepspeed_api(engine, zero, state_enum, mapping_helper):
    """Check interfaces our ZeRO-2 patch calls before allocating model weights."""
    signatures={}
    calls=(
        (engine,'save_checkpoint',(None,'path'),{'tag':'checkpoint'}),
        (engine,'load_checkpoint',(None,'path'),{'tag':'checkpoint'}),
        (engine,'zero_offload_param',(None,),{}),
        (engine,'zero_optimization_stage',(None,),{}),
        (engine,'get_global_grad_norm',(None,),{}),
        (zero,'_update_model_bit16_weights',(None,0),{}),
        (zero,'_link_all_hp_params',(None,),{}),
        (zero,'get_data_parallel_partitions',(None,None,0),{}),
        (zero,'state_dict',(None,),{}),
        (zero,'load_state_dict',(None,[]),{}),
    )
    for owner,name,args,kwargs in calls:
        fn=getattr(owner,name,None)
        if not callable(fn):raise RuntimeError(f'Missing DeepSpeed interface: {name}')
        signature=inspect.signature(fn)
        signature.bind(*args,**kwargs)
        signatures[name]=str(signature)
    for name in ('lp_params','hp_params','lp_grads','contiguous_grad_buffer','optim_states'):
        if getattr(state_enum,name,None) is None:
            raise RuntimeError(f'Missing DeepSpeed offload state: {name}')
    inspect.signature(mapping_helper).bind([])
    return signatures


def validate_results(root):
    root=Path(root);a=root/'continuous';b=root/'resumed'
    (root/'PREFLIGHT_COMPLETE.json').unlink(missing_ok=True)
    for run in (a,b):
        if not (run/'DRIVER_COMPLETE.json').is_file():
            raise RuntimeError(f'Driver incomplete: {run}')
        if not (run/'checkpoints/checkpoint-1/COMPLETE.json').is_file():
            raise RuntimeError(f'Final checkpoint incomplete: {run}')
    first=read(a/'bp_weight_witness.jsonl');second=read(b/'bp_weight_witness.jsonl')
    assert [(r['step'],r['phase']) for r in first]==[(0,'before_rollout'),(1,'before_rollout'),(2,'final')]
    assert [(r['step'],r['phase']) for r in second]==[(1,'before_rollout'),(2,'final')]
    if first[1]['actor'] != second[0]['actor']:
        raise RuntimeError('Restored parameters/master/Adam/scheduler/RNG differ from checkpoint-one witness')
    if first[0]['actor'][0]['weights']==first[-1]['actor'][0]['weights']:
        raise RuntimeError('No sampled BF16 parameter change after two updates; inspect rewards, LR and gradients')
    for r in first+second:
        if any(s['global_steps']!=r['step'] for s in r['actor']):
            raise RuntimeError('Actual optimizer counter does not match policy version')
        if any(s['weights'] != r['actor'][0]['weights'] for s in r['inference']):
            raise RuntimeError('Sampling replica is stale')
        if r['reference']!=first[0]['reference']:
            raise RuntimeError('Reference changed across continuation')
    for run,steps in ((a,(0,1)),(b,(1,))):
        for step in steps:
            rows=read(run/f'bp_rollout_train_{step}.jsonl')
            if len(rows)!=128 or len({r['sample_seed'] for r in rows})!=128:
                raise RuntimeError('Missing/duplicate independent training samples')
            from collections import Counter
            if set(Counter(r['task_id'] for r in rows).values())!={8}:
                raise RuntimeError('Broken eight-answer reward groups')
        final=read(run/'bp_rollout_final_2.jsonl')
        if len(final)!=16 or any(r['policy_optimizer_steps']!=2 for r in final):
            raise RuntimeError('Missing generation after the second weight update')
    r1=read(a/'bp_rollout_train_1.jsonl');r2=read(b/'bp_rollout_train_1.jsonl')
    if {(r['task_id'],r['sample_seed']) for r in r1}!={(r['task_id'],r['sample_seed']) for r in r2}:
        raise RuntimeError('Continuation changed the prompt/seed schedule')
    result=dict(status='passed',continuous_updates=2,resumed_updates=1,
                restored_optimizer_steps=1,final_optimizer_steps=2,
                sampled_parameter_change=True,loaded_vllm_weights_match=True,
                master_optimizer_scheduler_rng_restored=True,
                warning='Sampled weight/state witnesses; no claim of full-bitwise training reproducibility or training quality.')
    (root/'PREFLIGHT_COMPLETE.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def environment(root, backend='megatron', check_fused=False):
    names=('torch','vllm','transformers','deepspeed','ray','datasets','hydra-core','dacite','tensordict','accelerate')
    versions={}
    for name in names:
        try:versions[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:versions[name]=None
    record=dict(python=sys.executable,versions=versions,cuda_visible_devices=os.environ.get('CUDA_VISIBLE_DEVICES'))
    (root/'environment.json').write_text(json.dumps(record,indent=2)+'\n')
    if any(v is None for v in versions.values()):
        raise RuntimeError('Missing training packages; see environment.json. No packages were installed or changed.')
    if backend not in ('megatron','deepspeed'):raise ValueError(backend)
    validate_versions(versions,backend=backend)
    record['training_backend']=backend+'_train'
    try:
        if backend=='megatron':
            from training.b_sft.bp_megatron import validate_environment
            record['megatron_api']=validate_environment()
        else:
            from deepspeed import DeepSpeedEngine
            from deepspeed.runtime.zero.stage_1_and_2 import DeepSpeedZeroOptimizer
            from deepspeed.runtime.zero.offload_config import OffloadStateTypeEnum
            from deepspeed.runtime.zero.utils import get_mapping_to_flat_buffer
            record['deepspeed_api']=validate_deepspeed_api(DeepSpeedEngine,DeepSpeedZeroOptimizer,
                OffloadStateTypeEnum,get_mapping_to_flat_buffer)
    except Exception as exc:
        record[backend+'_error']=str(exc)
        (root/'environment.json').write_text(json.dumps(record,indent=2)+'\n')
        raise
    (root/'environment.json').write_text(json.dumps(record,indent=2)+'\n')
    import torch
    from training.b_sft.prepare_b_grpo_nccl import verify_loaded_library
    record['nccl_loaded']=verify_loaded_library(os.environ['NCCL_LIBRARY'])
    record['ld_preload']=os.environ.get('LD_PRELOAD')
    record['cuda_home']=os.environ.get('CUDA_HOME')
    (root/'environment.json').write_text(json.dumps(record,indent=2)+'\n')
    if torch.cuda.device_count()!=2:
        raise RuntimeError('Exactly two assigned visible GPUs are required')
    record['gpus']=[dict(name=torch.cuda.get_device_name(i),bytes=torch.cuda.get_device_properties(i).total_memory) for i in range(2)]
    (root/'environment.json').write_text(json.dumps(record,indent=2)+'\n')
    if any(g['bytes']<38*1024**3 for g in record['gpus']):
        raise RuntimeError('Expected two A100-40G-class GPUs')
    if check_fused:
        from training.b_sft.bp_memory import check_fused_adamw
        record['fused_adamw_cuda_check']=check_fused_adamw()
        (root/'environment.json').write_text(json.dumps(record,indent=2)+'\n')
    from roll.pipeline.rlvr.rlvr_pipeline import RLVRPipeline
    from training.b_sft.social_bp_reward_worker import SocialBPRewardWorker
    from vllm.entrypoints.openai.tool_parsers.hermes_tool_parser import Hermes2ProToolParser


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--model',default='/raid/chenjiahao/mas/models/Qwen3-4B-Instruct-2507')
    parser.add_argument('--data',default='examples/social_bp/data_two_a100_v1')
    parser.add_argument('--validate-results',action='store_true')
    args=parser.parse_args();root=args.output.resolve()
    if args.validate_results:
        print(json.dumps(validate_results(root),indent=2));return
    root.mkdir(parents=True,exist_ok=False)
    monitor=None;monitor_file=None
    def run(command,log,env=None):
        print('Running: '+' '.join(command),flush=True)
        with (root/log).open('w') as stream:
            process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,env=env)
            diagnostics=None;diagnostic_log=None
            try:
                if log in ('continuous.log','resumed.log'):
                    diagnostic_log=(root/(log+'.monitor.log')).open('w')
                    diagnostics=subprocess.Popen([sys.executable,'-u','-m','training.b_sft.bp_runtime_monitor',
                        '--pid',str(process.pid),'--output',str(root/(log+'.resources.jsonl'))],
                        stdout=diagnostic_log,stderr=subprocess.STDOUT,env=env)
                for line in process.stdout:
                    stream.write(line);stream.flush();print(line,end='',flush=True)
                status=process.wait()
                if status:raise RuntimeError(f'Command failed ({status}); inspect {log}')
            except BaseException:
                process.terminate()
                try: process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    process.kill();process.wait()
                raise
            finally:
                if diagnostics is not None:
                    diagnostics.terminate()
                    try: diagnostics.wait(timeout=5)
                    except subprocess.TimeoutExpired: diagnostics.kill();diagnostics.wait()
                if diagnostic_log is not None: diagnostic_log.close()
    try:
        # CPU-only contracts fail before CUDA checks, Ray or model initialization.
        run([sys.executable,'-m','training.b_sft.bp_cpu_preflight'],'cpu_contract.log')
        # CUDA/import checks in a separate process; release its GPU contexts before training.
        check_env=os.environ.copy();check_env['ROLL_LOG_DIR']=str(root/'environment_logs')
        run([sys.executable,'-c','from pathlib import Path; from training.b_sft.bp_two_gpu_preflight import environment; environment(Path(__import__("sys").argv[1]))',str(root)],'environment.log',check_env)
        monitor_file=(root/'gpu.csv').open('w')
        monitor=subprocess.Popen(['nvidia-smi','--id='+os.environ['CUDA_VISIBLE_DEVICES'],
            '--query-gpu=timestamp,index,utilization.gpu,memory.used,memory.total,power.draw',
            '--format=csv','-l','5'],stdout=monitor_file,stderr=subprocess.STDOUT)
        export=root/'export'
        run([sys.executable,'-m','training.b_sft.social_bp_grpo','--data',args.data,'--out',str(export),'--model',args.model],'export.log')
        exported=read(export/'train.jsonl')
        canaries=[r for r in exported if json.loads(r['ground_truth'])['training_source']=='l0']
        canaries.append(next(r for r in exported if json.loads(r['ground_truth'])['task']=='P'))
        (export/'smoke_validation.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in canaries))
        manifest=json.loads((export/'manifest.json').read_text())
        if manifest['max_prompt_tokens']>2048:
            raise RuntimeError('Frozen prompts exceed two-GPU padding budget; do not truncate')
        for name in ('continuous','resumed'):
            env=os.environ.copy();env.update(BP_RUN_DIR=str(root/name),BP_EXPORT_DIR=str(export),BP_MODEL=args.model,
                                            ROLL_OUTPUT_DIR=str(root/name),ROLL_LOG_DIR=str(root/name/'logs'))
            command=[sys.executable,'-u','-m','training.b_sft.run_bp_two_gpu']
            if name=='resumed':
                checkpoint=root/'continuous/checkpoints/checkpoint-0'
                if not (checkpoint/'COMPLETE.json').is_file():raise RuntimeError('First-update checkpoint missing')
                command += ['--resume-from',str(checkpoint)]
            run(command,name+'.log',env)
        print(json.dumps(validate_results(root),indent=2))
    except BaseException as exc:
        (root/'PREFLIGHT_FAILED.json').write_text(json.dumps(dict(error=repr(exc),training_ready=False),indent=2)+'\n')
        raise
    finally:
        if monitor is not None:
            monitor.terminate();monitor.wait(timeout=10)
        if monitor_file is not None:monitor_file.close()


if __name__=='__main__':main()
