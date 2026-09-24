"""One local Ray job; no shared head, package installation or model download."""
import numpy as _numpy

# Megatron Core 0.12.3 still calls the NumPy 1.x alias ``np.product``;
# NumPy 2.x removed it. Install the alias before Megatron is imported.
if not hasattr(_numpy, "product"):
    _numpy.product = _numpy.prod

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


def data_manifest_sha256():
    from training.social_mixed.core import DATA
    return hashlib.sha256((DATA/'manifest.json').read_bytes()).hexdigest()


def verify_bundle():
    # Retain compatibility with archive launchers; prefer Git when available.
    from training.social_mixed.source_version import verify_source
    return verify_source(ROOT)


def configuration(arm, seed=42, resume=None):
    from hydra import initialize_config_dir, compose
    from omegaconf import OmegaConf
    from dacite import from_dict
    from roll.pipeline.rlvr.rlvr_config import RLVRConfig
    with initialize_config_dir(config_dir=str(ROOT/'examples/social_mixed'),version_base=None):
        value=compose(config_name=arm)
        value.seed=seed
        from training.social_mixed.hardware import apply
        apply(value,os.environ.get("SOCIAL_GPU_PROFILE","h100-96"))
        # Resident CalBench uses the formal 32K inference context; training
        # optimizer batches retain the independent 4096-token sequence limit.
        if arm in ('selfplay','outcome','conditioned','decomposed'):
            value.actor_infer.strategy_args.strategy_config.max_model_len=32768
        if os.environ.get('SOCIAL_MICRO_BANK','0')=='1':
            value.max_steps=40
            value.save_steps=10
            value.eval_steps=10
        # SocialPipeline performs exactly one optimizer update per collected
        # batch. Generic RLVR derives steps from its fixed rollout_batch_size
        # (a placeholder here), which floors to zero for microbatch > 1.
        if resume:value.resume_from_checkpoint=str(Path(resume).resolve())
        resolved=OmegaConf.to_container(value,resolve=True)
    resolved["actor_train"]["training_args"]["max_steps"]=int(resolved["max_steps"])
    config=from_dict(RLVRConfig,resolved)
    assert config.actor_train.world_size==config.num_gpus_per_node
    assert config.actor_infer.world_size==config.num_gpus_per_node and config.reference.world_size==config.num_gpus_per_node
    assert config.actor_train.training_args.max_steps==config.max_steps
    return config,resolved


def environment(root):
    versions={}
    for name in ('torch','transformers','vllm','ray','megatron-core','transformer-engine','flash-attn'):
        try:versions[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:versions[name]=None
    (root/'environment.json').write_text(json.dumps(versions,indent=2)+'\n')
    from training.b_sft.bp_megatron import validate_environment
    from training.social_mixed.hardware import PROFILES
    profile=PROFILES[os.environ.get('SOCIAL_GPU_PROFILE','h100-96')]
    details=validate_environment(tensor_parallel_size=profile['tp'])
    # Fail on incompatible adapter before loading any weights.
    importlib.import_module('roll.third_party.vllm')
    from vllm import SamplingParams
    SamplingParams(n=1,temperature=1.0,top_p=1.0,top_k=-1,max_tokens=1024,logprobs=0,seed=42)
    import torch
    if torch.cuda.device_count()!=profile['gpus']:
        raise RuntimeError(f'Expected {profile["gpus"]} allocated GPUs, visible={torch.cuda.device_count()}')
    details['gpus']=[dict(name=torch.cuda.get_device_name(i),memory=torch.cuda.get_device_properties(i).total_memory) for i in range(profile['gpus'])]
    (root/'environment_details.json').write_text(json.dumps(details,indent=2)+'\n')


def validate_resume(path, options, model):
    path=Path(path)
    if not (path/'COMPLETE.json').is_file():
        raise ValueError('Resume requires a completed native Megatron checkpoint')
    from training.social_mixed.hardware import PROFILES
    expected=PROFILES[options.get('gpu_profile','h100-96')]
    checkpoint=json.loads((path/'COMPLETE.json').read_text())
    if checkpoint.get('tp')!=expected['tp'] or checkpoint.get('world_size')!=expected['gpus']:
        raise ValueError('Native resume requires the same TP/world size; TP=2 checkpoints cannot resume on single H200 TP=1')
    old=json.loads((path.parents[1]/'experiment.json').read_text())
    from training.social_mixed.core import PROTOCOL_VERSION
    if old.get('advantage_version')!=PROTOCOL_VERSION or old['options'].get('protocol_coefficient')!=options.get('protocol_coefficient'):
        raise ValueError('Resume must preserve protocol advantage version and coefficient; use a new experiment for changed objectives')
    if options.get('recipe_version'):
        if old['options'].get('recipe_version')!=options['recipe_version'] or old['options'].get('total_tokens')!=options['total_tokens']:
            raise ValueError('Resume must preserve recipe and cosine token horizon; start a new stage')
    if old['options'].get('micro_bank_sha256')!=options.get('micro_bank_sha256'):
        raise ValueError('Micro bank changed')
    if old['options'].get('interaction_bank_sha256')!=options.get('interaction_bank_sha256'):
        raise ValueError('Interaction bank changed; start a new stage')
    if old['options'].get('compact_bank_sha256')!=options.get('compact_bank_sha256'):
        raise ValueError('Training pool changed on resume')
    if old['options'].get('paired_bank_sha256')!=options.get('paired_bank_sha256'):
        raise ValueError('Paired bank changed on resume')
    if options.get('recipe')=='reasoning' or old['options'].get('recipe')=='reasoning':
        for key in ('normalization', 'recipe', 'max_behavior_logprob_delta', 'max_behavior_clip_fraction'):
            if old['options'].get(key)!=options.get(key):
                raise ValueError('Resume must preserve '+key)
    keys=('arm','seed','tokens_per_update')
    if any(old['options'][k]!=options[k] for k in keys) or old['model']!=model:
        raise ValueError('Resume must preserve experiment arm, seed, batch budget and base reference')
    manifest=data_manifest_sha256()
    if old['data_manifest_sha256']!=manifest:
        raise ValueError('Resume data differs from original experiment')


def validate_course_coverage(data, arm):
    if arm not in ('mixed','bp','b_only','p_only'):
        return
    required={'B1','B2','B3'} if arm=='b_only' else {'P1','P2','P3','P4'} if arm=='p_only' else {'B1','B2','B3','P1','P2','P3','P4'}
    present={t.get('kernel') for t in data['bp_train']}
    missing=sorted(required-present)
    if missing:
        raise ValueError('Incomplete B/P curriculum; missing kernels: '+', '.join(missing)+
                         '. Restore complete reasoning and contrast coverage before formal training.')


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--arm',choices=['selfplay','bp','b_only','p_only','outcome','conditioned','decomposed'],required=True)
    cli.add_argument('--recipe',choices=['reasoning','legacy'],default=None)
    cli.add_argument('--normalization',choices=['centered_fixed','standard_sequence'],default='standard_sequence')
    cli.add_argument('--max-behavior-logprob-delta',type=float,default=.05)
    cli.add_argument('--max-behavior-clip-fraction',type=float,default=.01)
    cli.add_argument('--seed',type=int,default=42)
    cli.add_argument('--total-tokens',type=int,default=6553600)
    cli.add_argument('--tokens-per-update',type=int,default=65536)
    cli.add_argument('--keep-checkpoints',type=int,default=1)
    cli.add_argument('--pause-after-updates',type=int)
    cli.add_argument('--protocol-coefficient',type=float,default=0.2)
    cli.add_argument('--resume')
    cli.add_argument('--diagnose-probabilities',action='store_true')
    cli.add_argument('--check-only',action='store_true')
    args=cli.parse_args()
    from training.social_mixed.reasoning_training import ARMS
    args.recipe=args.recipe or ('reasoning' if args.arm in ARMS else 'legacy')
    if args.recipe=='reasoning':
        if args.arm not in ARMS:raise ValueError('Reasoning recipe requires one of SP/O/C/D')
        if args.arm!='decomposed' and os.environ.get('SOCIAL_INTERACTION_BANK','0')!='1' and (args.tokens_per_update<57344 or args.total_tokens%args.tokens_per_update):
            raise ValueError('Reasoning uses complete nominal token blocks >=57344 tokens')
        if not (0<args.max_behavior_logprob_delta<1 and 0<args.max_behavior_clip_fraction<1):
            raise ValueError('Probability acceptance thresholds must be in (0,1)')
    elif args.arm=='conditioned':raise ValueError('C requires the reasoning recipe')
    if not _numpy.isfinite(args.protocol_coefficient) or args.protocol_coefficient<=0:
        raise ValueError('Protocol coefficient must be finite and positive')
    source_hash=verify_bundle()
    from training.social_mixed.core import load_data, arm_mixture
    data = load_data()
    if not args.check_only:validate_course_coverage(data,args.arm)
    if args.arm in ('mixed','bp','b_only','p_only'):
        from training.b_sft.decision_policy import VERSION as objective_version
        if any(t.get('objective_version') != objective_version or not t.get('training_ready')
               for split in ('train', 'validation') for t in data['bp_'+split]):
            raise ValueError('B/P data is not approved under the active label contract. '
                             'Complete response_only_v1 migration and curriculum review before training.')
    options=vars(args).copy()
    options['interaction_bank']=os.environ.get('SOCIAL_INTERACTION_BANK','0')=='1'
    options['micro_bank']=os.environ.get('SOCIAL_MICRO_BANK','0')=='1'
    if options['micro_bank']:
        if args.arm!='decomposed' or args.recipe!='reasoning' or options['interaction_bank']:
            raise ValueError('Micro requires isolated reasoning decomposed launcher')
        from training.social_mixed.micro_training import identity
        options['micro_bank_sha256']=identity()
        options['keep_checkpoints']=4

    if options['interaction_bank']:
        if args.recipe!='reasoning' or args.arm not in ('outcome','conditioned','decomposed'):raise ValueError('Interaction bank supports reasoning O/C/D only')
        if args.normalization!='standard_sequence' or args.protocol_coefficient!=.2:raise ValueError('Interaction recipe requires standard_sequence and protocol coefficient 0.2')
        from training.social_mixed.interaction_bank import load as interaction_load
        _,options['interaction_bank_sha256']=interaction_load()
    from training.social_mixed.stabilization import VERSION as recipe_version
    if args.recipe=='reasoning':
        from training.social_mixed.reasoning_training import VERSION as recipe_version
    options['recipe_version']=recipe_version
    if args.recipe=='reasoning' and args.arm in ('outcome','conditioned','decomposed'):
        from training.social_mixed.coverage_sampling import VERSION as coverage_version
        options['coverage_version']=coverage_version
        if args.arm=='decomposed':options['candidate_groups_per_update']={'O':4,'B':4,'Pplus':4}
        options['difficulty_version']='within-view-curriculum-v2'
        from training.social_mixed.compact_bank import load as compact_load
        _, _, options['compact_bank_sha256'] = compact_load()
        options['training_pool']='compact-200-operations-v2'
    if options['interaction_bank']:
        from training.social_mixed.interaction_training import VERSION as interaction_version
        options['recipe_version']=interaction_version
        options['training_pool']='interaction-o100-b-structure-v1'
        options['candidate_groups_per_update']={'decomposed':{'O':4,'B':4,'Pplus':4},'conditioned':{'O':8,'Pplus':4},'outcome':{'O':4}}[args.arm]
    if args.recipe=='reasoning' or args.arm in ('outcome','decomposed'):
        if args.recipe=='reasoning':
            from training.social_mixed.reasoning_bank import PATH,load
        else:
            from training.social_mixed.paired_bank import PATH,load
        load('train')
        load('validation')
        options['paired_bank_sha256']=__import__('hashlib').sha256((PATH/'manifest.json').read_bytes()).hexdigest()
    options['gpu_profile']=os.environ.get('SOCIAL_GPU_PROFILE','h100-96')
    if options['micro_bank']:
        from training.social_mixed.micro_training import VERSION
        from examples.social_mixed.micro_learning_v1 import dataset as micro_dataset
        options.update(recipe_version=VERSION,training_pool=micro_dataset.ROOT.name,candidate_groups_per_update={'all':len(micro_dataset.batch(0))//8})
    if args.total_tokens<1 or args.tokens_per_update<1:raise ValueError('Token budgets must be positive')
    if args.pause_after_updates is not None and args.pause_after_updates<1:
        raise ValueError('pause-after-updates must be positive')
    if args.keep_checkpoints<1:raise ValueError('Keep at least one complete recovery point')
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
    if os.environ.get('SOCIAL_GPU_PREFLIGHT') == '1':
        from training.social_mixed.soc_gpu_check import run as gpu_check
        gpu_check(root)
    print('ENVIRONMENT_CHECK_BEGIN',flush=True)
    environment(root)
    print('ENVIRONMENT_CHECK_PASSED',flush=True)
    (root/'experiment.json').write_text(json.dumps(dict(options=options,model=model,source_version=source_hash,source_commit=source_hash.get('commit'),source_bundle_sha256=source_hash.get('sha256'),
        data_manifest_sha256=data_manifest_sha256(),
        dataset=__import__('training.social_mixed.core',fromlist=['DATA']).DATA.name,
        allowed_completion_modes=['binary','linear'],
        execution_profile=__import__('training.social_mixed.hardware',fromlist=['PROFILES']).PROFILES[options['gpu_profile']],
        reward='B/P binary; SP own terminal utility; invalid/truncated calls use independent negative advantage instead of task advantage',
        advantage_version=__import__('training.social_mixed.core',fromlist=['PROTOCOL_VERSION']).PROTOCOL_VERSION,
        mixture=arm_mixture(args.arm),
        grouping=('Fixed candidate slots, legal-only centered advantages; SP historical baseline' if args.recipe=='reasoning'
                  else 'B/P task; selfplay reset and player seat across replicas'),
        budget='Generated response tokens entering training, including retries; finish current groups at boundary'),indent=2)+'\n')
    if args.check_only:
        done.set();return
    import ray
    from roll.utils.constants import RAY_NAMESPACE
    temp=Path(tempfile.mkdtemp(prefix='sm-',dir=os.environ.get('SOCIAL_RAY_ROOT','/tmp')))
    (temp/'spill').mkdir()
    try:
        ray.init(address='local',num_cpus=int(os.environ.get('SLURM_CPUS_PER_TASK','24')),num_gpus=cfg.num_gpus_per_node,
                 include_dashboard=False,_node_ip_address='127.0.0.1',_temp_dir=str(temp),
                 object_store_memory=2*1024**3,namespace=RAY_NAMESPACE,
                 _system_config={'object_spilling_config':json.dumps({'type':'filesystem','params':{'directory_path':str(temp/'spill')}})})
        from training.social_mixed.pipeline import SocialPipeline
        pipeline=SocialPipeline(cfg,options)
        if args.diagnose_probabilities:
            if args.resume:raise ValueError('Probability diagnosis starts from the original model, not resume')
            from training.social_mixed.probability_diagnostic import run as diagnose
            diagnose(pipeline)
        else:
            pipeline.run()
    finally:
        done.set()
        faulthandler.cancel_dump_traceback_later()
        ray.shutdown()


if __name__=='__main__':main()
