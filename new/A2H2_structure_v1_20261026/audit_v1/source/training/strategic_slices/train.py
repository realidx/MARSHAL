"""Launch slices or SP on one frozen shared-parent dataset (CPU --check-only)."""
import argparse
import json
import os
from pathlib import Path
import tempfile

from .common import Dataset, VERSION, write_json, file_hash, digest


def validate_resume(path, contract, profile):
    complete = json.loads((path / 'COMPLETE.json').read_text())
    if complete.get('tp') != profile['tp'] or complete.get('world_size') != profile['gpus']:
        raise ValueError('Native resume requires identical TP/world size')
    old = json.loads((path.parents[1] / 'experiment.json').read_text())
    if old['run_contract'] != contract:
        raise ValueError('Resume must preserve arm, data, model, token horizon, replicas and validation protocol')


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--data', type=Path, required=True)
    cli.add_argument('--arm', choices=('slices', 'selfplay'), required=True)
    cli.add_argument('--model', type=Path)
    cli.add_argument('--output', type=Path)
    cli.add_argument('--profile', choices=('h100-96', 'h100-47', 'h200-141'), default='h100-96')
    cli.add_argument('--seed', type=int, default=42)
    cli.add_argument('--replicas', type=int, default=4)
    cli.add_argument('--concurrency', type=int, default=32)
    cli.add_argument('--total-tokens', type=int, default=6553600)
    cli.add_argument('--tokens-per-update', type=int, default=65536)
    cli.add_argument('--eval-every', type=int, default=10)
    cli.add_argument('--validation-repeats', type=int, default=1)
    cli.add_argument('--max-steps', type=int, default=1000)
    cli.add_argument('--keep-checkpoints', type=int, default=2)
    cli.add_argument('--pause-after-updates', type=int)
    cli.add_argument('--resume', type=Path)
    cli.add_argument('--check-only', action='store_true')
    args = cli.parse_args()
    if min(args.total_tokens, args.tokens_per_update, args.eval_every, args.validation_repeats, args.max_steps,
           args.concurrency, args.keep_checkpoints) < 1 or args.replicas < 2:
        cli.error('Positive budgets/cadences and >=2 replicas required')
    if args.pause_after_updates is not None and args.pause_after_updates < 1:
        cli.error('--pause-after-updates must be positive')
    dataset = Dataset(args.data)
    report = dict(arm=args.arm, dataset_sha256=dataset.sha, train_parents=len(dataset.parents['train']),
                  validation_parents=len(dataset.parents['validation']), train_slices=len(dataset.slices['train']),
                  test_loaded=False, tokenizer_checked=False, gpu_checked=False,
                  reference_policy=dataset.manifest['config'].get('reference_policy', 'synchronous'),
                  training_contract=dataset.manifest.get('training_contract'),
                  total_tokens=args.total_tokens, replicas=args.replicas)
    if args.check_only:
        # Exercise loading and native reference reconstruction on each player-count stratum.
        examples = {}
        for parent in dataset.parents['train']:
            examples.setdefault(parent['players'], parent)
        for parent in examples.values():
            dataset.reference(parent)
        print(json.dumps(report, indent=2)); return
    if args.model is None or args.output is None:
        cli.error('--model and --output are required for GPU training')
    if not (args.model / 'config.json').is_file():
        raise FileNotFoundError('Supply local Qwen3-4B-Instruct-2507 weights')
    if json.loads((args.model / 'config.json').read_text()).get('model_type') != 'qwen3':
        raise ValueError('This configuration targets Qwen3')
    options = vars(args).copy()
    for key in ('data', 'model', 'output', 'resume'):
        if options[key] is not None:
            options[key] = str(options[key].resolve())
    options.update(recipe='strategic_slices', dataset_sha256=dataset.sha,
                   max_behavior_logprob_delta=.05, max_behavior_clip_fraction=.01)
    model_files = [p for p in args.model.iterdir() if p.is_file() and (
        p.suffix in ('.safetensors', '.bin') or p.name in ('config.json', 'tokenizer.json', 'tokenizer_config.json'))]
    if not any(p.suffix in ('.safetensors', '.bin') for p in model_files):
        raise ValueError('Local base model contains no weight files')
    model_hashes = {p.name: file_hash(p) for p in sorted(model_files)}
    options['model_sha256'] = digest(model_hashes)
    contract = {k: options[k] for k in ('arm', 'dataset_sha256', 'model', 'model_sha256', 'profile', 'seed', 'replicas',
                                       'total_tokens', 'tokens_per_update', 'eval_every', 'validation_repeats', 'concurrency', 'max_steps')}
    root = args.output.resolve(); root.mkdir(parents=True, exist_ok=False)
    (root / 'logs').mkdir()
    write_json(root / 'model_hashes.json', model_hashes)
    os.environ.update(SOCIAL_MODEL=str(args.model.resolve()), SOCIAL_GPU_PROFILE=args.profile,
                      ROLL_OUTPUT_DIR=str(root), ROLL_LOG_DIR=str(root / 'logs'),
                      VLLM_BATCH_INVARIANT='0')
    from training.social_mixed.run import configuration, environment
    from training.social_mixed.hardware import PROFILES
    if args.resume:
        validate_resume(args.resume.resolve(), contract, PROFILES[args.profile])
    cfg, resolved = configuration('selfplay', args.seed, str(args.resume.resolve()) if args.resume else None)
    cfg.eval_steps = cfg.save_steps = args.eval_every
    cfg.exp_name = 'strategic_' + args.arm + '_4b'
    cfg.max_steps = cfg.actor_train.training_args.max_steps = args.max_steps
    # Train and validate with the identical 4096/1024 prompt/response limits.
    cfg.actor_infer.strategy_args.strategy_config['max_model_len'] = 4096
    write_json(root / 'resolved_config.json', cfg.to_dict())
    # Bind actual source, including this new uncommitted task, without requiring unrelated paper edits to be committed.
    source_root = Path(__file__).resolve().parents[2]
    sources = {str(p.relative_to(source_root)): file_hash(p) for folder in
               ('training/strategic_slices', 'training/social_mixed', 'training/b_sft', 'new/benac_slice_pilot', 'roll', 'mcore_adapter/src', 'third_party/negotiation_benchmark/src')
               for p in (source_root / folder).rglob('*.py')}
    write_json(root / 'source_manifest.json', sources)
    write_json(root / 'experiment.json', dict(run_contract=contract, options=options, model=str(args.model.resolve()),
        checks=report, source_manifest_sha256=file_hash(root / 'source_manifest.json'),
        primary_checkpoint='final', reward=(dataset.manifest.get('training_contract') or
            'Own terminal utility; same independent invalid-call advantage -0.2 in both arms.'),
        budget='All training generated response tokens, including invalid/truncated responses; finish complete replica groups. Validation/oracle cost separate.',
        sampling='Shuffled uniform parent cycles; slices uniformly within selected parent; hidden world shared across replicas within group.',
        failed_groups='No task advantage if any replica fails; only observed invalid-call protocol advantage.'))
    if os.environ.get('SOCIAL_GPU_PREFLIGHT') == '1':
        from training.social_mixed.soc_gpu_check import run as gpu_check
        gpu_check(root)
    environment(root)
    import ray
    from roll.utils.constants import RAY_NAMESPACE
    temp = Path(tempfile.mkdtemp(prefix='slices-ray-', dir=os.environ.get('SOCIAL_RAY_ROOT', '/tmp')))
    (temp / 'spill').mkdir()
    try:
        ray.init(address='local', num_cpus=int(os.environ.get('SLURM_CPUS_PER_TASK', '24')),
                 num_gpus=cfg.num_gpus_per_node, include_dashboard=False, _node_ip_address='127.0.0.1',
                 _temp_dir=str(temp), object_store_memory=2 * 1024**3, namespace=RAY_NAMESPACE,
                 _system_config={'object_spilling_config': json.dumps({'type': 'filesystem', 'params': {'directory_path': str(temp / 'spill')}})})
        from .pipeline import SlicePipeline
        SlicePipeline(cfg, options).run()
    finally:
        ray.shutdown()


if __name__ == '__main__':
    main()
