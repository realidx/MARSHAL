"""Train the selected terminal windows with same-node continuous oracle GRPO.

CPU --check-only/--mock are local. Actual training requires an existing Slurm
GPU allocation; this entry never submits jobs or installs/downloads anything.
"""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import tempfile

from .common import digest,file_hash,write_json,write_rows
from .terminal_training import TrainingData,Collector,CONTRACT,VERSION,ensure,mock_generate
from .terminal_training_checkpoints import SELECTION
from .terminal_training_schedule import DEFAULT_NODE_GROUPS_PER_UPDATE,DEFAULT_EVAL_TOKENS,DEFAULT_SAVE_TOKENS
from .evaluation_refill import VERSION as EVALUATION_SCHEDULER

ROOT=Path(__file__).resolve().parents[2]


def source_identity():
    sources={str(p.relative_to(ROOT)):file_hash(p) for folder in
        ('training/strategic_slices','training/social_mixed','training/b_sft','new/benac_slice_pilot',
         'roll','mcore_adapter/src','third_party/negotiation_benchmark/src') for p in sorted((ROOT/folder).rglob('*.py'))}
    for p in sorted((ROOT/'examples/social_mixed').glob('*.yaml')):
        sources[str(p.relative_to(ROOT))]=file_hash(p)
    return sources


def settings(cfg,args):
    cfg.sequence_length=args.context;cfg.prompt_length=args.context-args.max_tokens
    cfg.actor_infer.generating_args.max_new_tokens=args.max_tokens
    cfg.actor_infer.strategy_args.strategy_config['max_model_len']=args.context
    cfg.actor_infer.strategy_args.strategy_config['max_num_seqs']=args.concurrency
    # The terminal subclass controls token boundaries; the native writer must
    # accept every save it requests. Explicit update cadences remain available.
    cfg.eval_steps=args.eval_every or 1
    cfg.save_steps=args.save_every or 1
    cfg.max_steps=cfg.actor_train.training_args.max_steps=args.max_steps
    cfg.exp_name='terminal_node_regret_4b'
    return cfg


def validate_resume(path,contract,profile):
    marker=json.loads((path/'COMPLETE.json').read_text())
    old=json.loads((path.parents[1]/'experiment.json').read_text())
    ensure(marker.get('tp')==profile['tp'] and marker.get('world_size')==profile['gpus'],'Resume TP/world size differs')
    ensure(old['run_contract']==contract,'Resume must preserve data, reward, sources, budgets and sampling')


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--pool',type=Path,default=ROOT/'new/local_data/strategic_slices_oracle_consistent_candidates_v4')
    cli.add_argument('--selection',type=Path,default=ROOT/'new/local_data/strategic_slices_terminal_selected_v4')
    cli.add_argument('--model',type=Path,default=Path('/home/e/e1300530/models/Qwen3-4B-Instruct-2507'))
    cli.add_argument('--output',type=Path)
    cli.add_argument('--profile',choices=('h100-47','h100-96','h100-96-single','h200-141'),default='h100-47')
    cli.add_argument('--seed',type=int,default=42)
    cli.add_argument('--replicas',type=int,default=8)
    cli.add_argument('--concurrency',type=int,default=32)
    cli.add_argument('--max-tokens',type=int,default=1024)
    cli.add_argument('--context',type=int,default=16384)
    cli.add_argument('--total-tokens',type=int,default=6000000)
    cli.add_argument('--node-groups-per-update',type=int,default=DEFAULT_NODE_GROUPS_PER_UPDATE)
    cli.add_argument('--tree-cache-mb',type=int,default=512)
    cli.add_argument('--oracle-cache-mb',type=int,default=128)
    cli.add_argument('--max-steps',type=int,default=10000)
    cli.add_argument('--eval-every',type=int,help='Override token schedule with an update cadence (e.g. smoke)')
    cli.add_argument('--save-every',type=int,help='Independent update cadence override for recovery checkpoints')
    cli.add_argument('--eval-every-tokens',type=int,default=DEFAULT_EVAL_TOKENS)
    cli.add_argument('--save-every-tokens',type=int,default=DEFAULT_SAVE_TOKENS)
    cli.add_argument('--validation-repeats',type=int,default=1)
    cli.add_argument('--test-repeats',type=int,default=8,help='Fixed-seed instances per test slice/full-game role, final checkpoint only')
    cli.add_argument('--validation-limit',type=int,help='Smoke only: restrict validation questions/parents; never a full evaluation')
    cli.add_argument('--keep-checkpoints',type=int,choices=(2,),default=2,help='Best and latest/final; one directory when identical')
    cli.add_argument('--pause-after-updates',type=int)
    cli.add_argument('--resume',type=Path)
    cli.add_argument('--check-only',action='store_true')
    cli.add_argument('--mock',action='store_true')
    cli.add_argument('--mock-updates',type=int,default=1)
    args=cli.parse_args()
    ensure(args.replicas>=2 and 0<args.max_tokens<args.context,'Invalid replica/token limits')
    ensure(min(args.concurrency,args.total_tokens,args.node_groups_per_update,args.max_steps,args.eval_every_tokens,args.save_every_tokens,
        args.validation_repeats,args.test_repeats,args.keep_checkpoints,args.mock_updates)>0,'Budgets/cadences must be positive')
    ensure(all(v is None or v>0 for v in (args.eval_every,args.save_every)),'Update cadences must be positive')
    ensure(args.validation_limit is None or args.validation_limit>0,'Validation limit must be positive')
    ensure(args.pause_after_updates is None or args.pause_after_updates>0,'Pause boundary must be positive')
    ensure(args.tree_cache_mb>=0 and args.oracle_cache_mb>=0,'Cache budgets must be nonnegative')
    data=TrainingData(args.pool,args.selection,tree_cache_mb=args.tree_cache_mb,oracle_cache_mb=args.oracle_cache_mb)
    report=dict(version=VERSION,dataset_sha256=data.sha,train_slices=len(data.train),
        train_parents=len({r['parent_id'] for r in data.train}),validation_slices=len(data.validation),
        test_used_for_scoring=False,k_counts=dict(Counter(r['k'] for r in data.train)),contract=CONTRACT,
        replicas=args.replicas,concurrency=args.concurrency,temperature=1.,max_tokens=args.max_tokens,context=args.context,
        total_tokens=args.total_tokens,node_groups_per_update=args.node_groups_per_update,
        target_responses_per_update=args.node_groups_per_update*args.replicas,
        batch_overshoot_max_node_groups=max(r['k'] for r in data.train)-1,
        monitoring=dict(eval_every_tokens=args.eval_every_tokens,save_every_tokens=args.save_every_tokens,
            eval_every_updates=args.eval_every,save_every_updates=args.save_every,
            baseline=True,final=True,best_saved_immediately=True,evaluation_scheduler=EVALUATION_SCHEDULER),
        checkpoint_selection=SELECTION,checkpoint_retention='Best plus latest/final; deduplicate identical checkpoints.',
        final_test=dict(enabled=True,slices=len(data.test),parents=len({r['parent_id'] for r in data.test}),
            repeats=args.test_repeats,temperature=0.,training_budget_includes_test=False,evaluation_scheduler=EVALUATION_SCHEDULER),
        cpu_reuse=dict(tree_cache_mb=args.tree_cache_mb,oracle_cache_mb=args.oracle_cache_mb,
            oracle='Exact frozen-profile continuation cache; exhaustive scorer retained for audit',prompt='Per-stream 16MiB encoding cache'),
        model_path_checked=False,gpu_started=False,submitted=False)
    if args.check_only:
        print(json.dumps(report,indent=2));return
    ensure(args.output is not None,'--output is required')
    if args.mock:
        ensure(args.resume is None,'Mock has its own exact collector-state resume check')
        args.output.mkdir(parents=True,exist_ok=False)
        collector=Collector(data,mock_generate,seed=args.seed,replicas=args.replicas,concurrency=args.concurrency,
            max_tokens=args.max_tokens,context=args.context,node_groups_per_update=args.node_groups_per_update)
        all_metrics=[];seen=set()
        for step in range(args.mock_updates):
            rows,units,games,metrics=collector.collect(step,'slices',token_target=1)
            write_rows(args.output/f'calls-{step}.jsonl',rows);write_rows(args.output/f'node-groups-{step}.jsonl',units);write_rows(args.output/f'games-{step}.jsonl',games)
            seen.update(g['slice_id'] for g in games);all_metrics.append(metrics)
        state=collector.state;write_json(args.output/'collector.json',state)
        restored=Collector(data,mock_generate,seed=args.seed,replicas=args.replicas,concurrency=args.concurrency,
            max_tokens=args.max_tokens,context=args.context,node_groups_per_update=args.node_groups_per_update);restored.restore(state)
        a=collector.collect(args.mock_updates,'slices',token_target=1)
        b=restored.collect(args.mock_updates,'slices',token_target=1)
        ensure(a==b and collector.state==restored.state,'Collector resume changed the next group')
        write_json(args.output/'CHECK.json',dict(report,mock=True,updates=all_metrics,distinct_train_questions=len(seen),
            exact_next_collection_resume=True,new_model_calls=0,gpu_optimizer_tested=False))
        print(json.dumps(dict(mock=True,distinct_train_questions=len(seen),updates=len(all_metrics),exact_resume=True)))
        return
    ensure(os.environ.get('SLURM_JOB_ID') and os.environ.get('CUDA_VISIBLE_DEVICES'),
        'Actual training requires an existing Slurm GPU allocation')
    ensure((args.model/'config.json').is_file(),'Supply local model weights')
    ensure(json.loads((args.model/'config.json').read_text()).get('model_type')=='qwen3','Expected Qwen3 checkpoint')
    sources=source_identity()
    model_files=[p for p in args.model.iterdir() if p.is_file() and (
        p.suffix in ('.safetensors','.bin') or p.name in ('config.json','tokenizer.json','tokenizer_config.json'))]
    ensure(any(p.suffix in ('.safetensors','.bin') for p in model_files),'Missing local weights')
    model_hashes={p.name:file_hash(p) for p in sorted(model_files)}
    options=vars(args).copy()
    for key in ('pool','selection','model','output','resume'):
        if options[key] is not None:options[key]=str(options[key].resolve())
    options.update(arm='slices',recipe='strategic_slices',recipe_version=VERSION,dataset_sha256=data.sha,
        max_behavior_logprob_delta=.05,max_behavior_clip_fraction=.01)
    run_contract=dict(options={k:v for k,v in options.items() if k not in ('output','resume','check_only','mock','mock_updates','pause_after_updates')},
        reward=CONTRACT,checkpoint_selection=SELECTION,model_sha256=digest(model_hashes),source_sha256=digest(sources))
    from training.social_mixed.hardware import PROFILES
    if args.resume:validate_resume(args.resume.resolve(),run_contract,PROFILES[args.profile])
    args.output.mkdir(parents=True,exist_ok=False);(args.output/'logs').mkdir()
    root=args.output.resolve()
    os.environ.update(SOCIAL_MODEL=str(args.model.resolve()),SOCIAL_GPU_PROFILE=args.profile,
        ROLL_OUTPUT_DIR=str(root),ROLL_LOG_DIR=str(root/'logs'),VLLM_BATCH_INVARIANT='0')
    from training.social_mixed.run import configuration,environment
    cfg,_=configuration('selfplay',args.seed,str(args.resume.resolve()) if args.resume else None)
    settings(cfg,args)
    write_json(root/'resolved_config.json',cfg.to_dict());write_json(root/'model_hashes.json',model_hashes)
    write_json(root/'source_manifest.json',sources)
    write_json(root/'experiment.json',dict(run_contract=run_contract,options=options,checks=report,
        primary_checkpoint='final',reward=CONTRACT,validation_limit=args.validation_limit,
        gpu_validation='This launch must establish the 16K/1024 profile on actual hardware.'))
    if os.environ.get('SOCIAL_GPU_PREFLIGHT')=='1':
        from training.social_mixed.soc_gpu_check import run as gpu_check
        gpu_check(root)
    environment(root)
    import ray
    from roll.utils.constants import RAY_NAMESPACE
    temp=Path(tempfile.mkdtemp(prefix='terminal-train-ray-',dir=os.environ.get('SOCIAL_RAY_ROOT','/tmp')))
    (temp/'spill').mkdir()
    try:
        ray.init(address='local',num_cpus=int(os.environ.get('SLURM_CPUS_PER_TASK','24')),
            num_gpus=cfg.num_gpus_per_node,include_dashboard=False,_node_ip_address='127.0.0.1',_temp_dir=str(temp),
            object_store_memory=2*1024**3,namespace=RAY_NAMESPACE,
            _system_config={'object_spilling_config':json.dumps({'type':'filesystem','params':{'directory_path':str(temp/'spill')}})})
        from .terminal_training_pipeline import TerminalPipeline
        TerminalPipeline(cfg,options).run()
    finally:ray.shutdown()


if __name__=='__main__':main()
