"""One local Ray job; no shared head, package installation or model download."""
import argparse
import faulthandler
import hashlib
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time

ROOT=Path(__file__).resolve().parents[2]


def verify_bundle():
    manifest=ROOT/'examples/social_mixed/bundle_manifest.json'
    if not manifest.exists():
        raise FileNotFoundError('Prepare the source bundle before submitting the experiment')
    data=json.loads(manifest.read_text())
    for name,expected in data['files'].items():
        path=ROOT/name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
            raise ValueError(f'Incomplete or changed upload: {name}; regenerate the bundle')
    print(f'SOURCE_BUNDLE_VERIFIED files={len(data["files"])}',flush=True)
    return hashlib.sha256(manifest.read_bytes()).hexdigest()


def configuration(arm, seed=42, resume=None):
    from hydra import initialize_config_dir, compose
    from omegaconf import OmegaConf
    from dacite import from_dict
    from roll.pipeline.rlvr.rlvr_config import RLVRConfig
    with initialize_config_dir(config_dir=str(ROOT/'examples/social_mixed'),version_base=None):
        value=compose(config_name=arm)
        value.seed=seed
        if resume:value.resume_from_checkpoint=str(Path(resume).resolve())
        resolved=OmegaConf.to_container(value,resolve=True)
    config=from_dict(RLVRConfig,resolved)
    config.set_max_steps(config.max_steps)
    assert config.actor_train.world_size==2
    assert config.actor_infer.world_size==2 and config.reference.world_size==2
    assert config.actor_train.training_args.max_steps==config.max_steps
    return config,resolved


def environment(root):
    versions={}
    for name in ('torch','transformers','vllm','ray','megatron-core','transformer-engine','flash-attn'):
        try:versions[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:versions[name]=None
    (root/'environment.json').write_text(json.dumps(versions,indent=2)+'\n')
    from training.b_sft.bp_megatron import validate_environment
    details=validate_environment()
    # Fail on incompatible adapter before loading any weights.
    importlib.import_module('roll.third_party.vllm')
    from vllm import SamplingParams
    SamplingParams(n=1,temperature=1.0,top_p=1.0,top_k=-1,max_tokens=1024,logprobs=0,seed=42)
    import torch
    if torch.cuda.device_count()!=2:
        raise RuntimeError(f'Expected exactly two allocated GPUs, visible={torch.cuda.device_count()}')
    details['gpus']=[dict(name=torch.cuda.get_device_name(i),memory=torch.cuda.get_device_properties(i).total_memory) for i in range(2)]
    (root/'environment_details.json').write_text(json.dumps(details,indent=2)+'\n')


def validate_resume(path, options, model):
    path=Path(path)
    if not (path/'COMPLETE.json').is_file():
        raise ValueError('Resume requires a completed native Megatron checkpoint')
    old=json.loads((path.parents[1]/'experiment.json').read_text())
    keys=('arm','seed','tokens_per_update')
    if any(old['options'][k]!=options[k] for k in keys) or old['model']!=model:
        raise ValueError('Resume must preserve experiment arm, seed, batch budget and base reference')
    manifest=hashlib.sha256((ROOT/'examples/social_mixed/data/manifest.json').read_bytes()).hexdigest()
    if old['data_manifest_sha256']!=manifest:
        raise ValueError('Resume data differs from original experiment')


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--arm',choices=['mixed','selfplay'],required=True)
    cli.add_argument('--seed',type=int,default=42)
    cli.add_argument('--total-tokens',type=int,default=6553600)
    cli.add_argument('--tokens-per-update',type=int,default=65536)
    cli.add_argument('--keep-checkpoints',type=int,default=2)
    cli.add_argument('--resume')
    cli.add_argument('--check-only',action='store_true')
    args=cli.parse_args()
    source_hash=verify_bundle()
    from training.social_mixed.core import load_data
    load_data()
    options=vars(args).copy()
    if args.total_tokens<1 or args.tokens_per_update<1:raise ValueError('Token budgets must be positive')
    if args.keep_checkpoints<2:raise ValueError('Keep at least two complete recovery points')
    root=Path(os.environ['ROLL_OUTPUT_DIR']).resolve()
    root.mkdir(parents=True,exist_ok=True)
    if (root/'experiment.json').exists():raise FileExistsError('Use a fresh output directory, including on resume')
    model=os.environ['SOCIAL_MODEL']
    if not (Path(model)/'config.json').is_file():raise FileNotFoundError(f'Missing local model: {model}')
    cfg,resolved=configuration(args.arm,args.seed,args.resume)
    if args.resume:validate_resume(args.resume,options,model)
    (root/'resolved_config.json').write_text(json.dumps(resolved,indent=2)+'\n')
    faulthandler.enable()
    faulthandler.dump_traceback_later(300,repeat=True)
    done=threading.Event()
    def heartbeat():
        while not done.wait(30):
            print(json.dumps(dict(event='driver_alive',utc=time.time(),pid=os.getpid())),flush=True)
    threading.Thread(target=heartbeat,daemon=True).start()
    print('ENVIRONMENT_CHECK_BEGIN',flush=True)
    environment(root)
    print('ENVIRONMENT_CHECK_PASSED',flush=True)
    (root/'experiment.json').write_text(json.dumps(dict(options=options,model=model,source_bundle_sha256=source_hash,
        data_manifest_sha256=hashlib.sha256((ROOT/'examples/social_mixed/data/manifest.json').read_bytes()).hexdigest(),
        reward='B/P binary; own terminal utility plus separately recorded protocol cost',
        mixture={'B':.25,'P':.25,'selfplay':.5} if args.arm=='mixed' else {'selfplay':1.0},
        grouping='B/P task; selfplay reset and player seat across replicas',
        budget='Generated response tokens entering training, including retries; finish current groups at boundary'),indent=2)+'\n')
    if args.check_only:
        done.set();return
    import ray
    from roll.utils.constants import RAY_NAMESPACE
    temp=Path(tempfile.mkdtemp(prefix='sm-',dir=os.environ.get('SOCIAL_RAY_ROOT','/tmp')))
    (temp/'spill').mkdir()
    try:
        ray.init(address='local',num_cpus=int(os.environ.get('SLURM_CPUS_PER_TASK','24')),num_gpus=2,
                 include_dashboard=False,_node_ip_address='127.0.0.1',_temp_dir=str(temp),
                 object_store_memory=2*1024**3,namespace=RAY_NAMESPACE,
                 _system_config={'object_spilling_config':json.dumps({'type':'filesystem','params':{'directory_path':str(temp/'spill')}})})
        from training.social_mixed.pipeline import SocialPipeline
        pipeline=SocialPipeline(cfg,options)
        pipeline.run()
    finally:
        done.set()
        faulthandler.cancel_dump_traceback_later()
        ray.shutdown()


if __name__=='__main__':main()
