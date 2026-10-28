"""Run via torchrun --module training.b_sft.train. No ROLL/vLLM imports."""

import argparse
import atexit
import hashlib
import json
import os
import time
from pathlib import Path

from .data import ToolCollator, check_corpus_export, check_resume, check_split, encode_sample, load_records
from .monitor import ResourceMonitor
from .preflight import device_tokens
from .loss_backend import (FusedLossMixin, backend_options, package_versions,
                           register_zero3_fused_head, validate_liger_support, verify_patch)
from .generation import evaluation_interval, prepare_prompts, select_train_probe, select_validation_pairs
from .semantic import read_pairs, score_records, write_jsonl
from .semantic_callback import make_semantic_callback


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', required=True)
    parser.add_argument('--train-file', help='Required for train/benchmark; not read in eval mode')
    parser.add_argument('--eval-file', required=True, help='Validation split, never the held-out test split')
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--deepspeed', default='training/b_sft/configs/zero3_shared.json')
    parser.add_argument('--mode', choices=['benchmark', 'train', 'eval'], default='benchmark')
    parser.add_argument('--max-steps', type=int, default=None, help='Total optimizer steps, including resumed steps')
    parser.add_argument('--epochs', type=float, default=1)
    parser.add_argument('--max-length', type=int, default=4096)
    parser.add_argument('--gradient-accumulation', type=int, default=2)
    parser.add_argument('--learning-rate', type=float, default=5e-6)
    parser.add_argument('--loss-backend', choices=['liger', 'standard'], default='liger',
                        help='Fused LM head + CE (default), or original full-logits baseline')
    parser.add_argument('--save-steps', type=int, default=20)
    parser.add_argument('--checkpoint-policy', choices=('all-evals', 'best-and-periodic'), default='all-evals',
                        help='Legacy every-eval saves, or periodic saves plus new best/final/early-stop')
    parser.add_argument('--keep-checkpoints', type=int, default=2, help='At least two: protect best and newest')
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--semantic-eval', action='store_true', help='First-answer generation, reports and best-model selection')
    parser.add_argument('--fit-check', action='store_true',
                        help='Bounded same-question fitting diagnostic; no validation or generation during training')
    parser.add_argument('--skip-eval-loss', action='store_true', help='Semantic training: omit validation loss, including final duplicate pass')
    parser.add_argument('--validation-pairs-per-source', type=int, default=0,
                        help='Semantic training: fixed complete pair subset per validation source; 0 uses full split')
    parser.add_argument('--eval-every-fraction', type=float, default=0.25, help='Fraction of an epoch between semantic evaluations')
    parser.add_argument('--semantic-eval-steps', type=int, help='Explicit interval overriding the epoch fraction')
    parser.add_argument('--early-stopping-patience', type=int, default=3, help='Consecutive non-improvements; 0 disables stopping')
    parser.add_argument('--generation-max-new-tokens', type=int, default=128)
    parser.add_argument('--train-probe-size', type=int, default=32)
    parser.add_argument('--pairs-file', help='Public-history before/after pairs JSONL, used only for scoring')
    parser.add_argument('--eval-split', choices=('validation', 'test', 'ood_test'), default='validation',
                        help='test/ood_test are allowed only in standalone eval mode')
    parser.add_argument('--baseline-predictions', help='Standalone eval: original-model first answers on exactly this split')
    parser.add_argument('--reuse-baseline-run', help='Fresh semantic training: reuse verified step-0 predictions from an earlier run')
    parser.add_argument('--resume', help='Explicit Trainer checkpoint-N directory')
    parser.add_argument('--expected-world-size', type=int, default=None,
                        help='Optional assertion; otherwise infer from explicit CUDA_VISIBLE_DEVICES')
    cli = parser.parse_args(argv)
    if cli.fit_check and (cli.mode != 'train' or cli.semantic_eval or cli.validation_pairs_per_source
                          or cli.max_steps is None or cli.max_steps <= 0):
        parser.error('--fit-check requires train mode, explicit positive max-steps, and no semantic evaluation/subsetting')
    if cli.reuse_baseline_run and (cli.mode != 'train' or not cli.semantic_eval or cli.resume
                                  or cli.baseline_predictions or cli.train_probe_size or not cli.skip_eval_loss):
        parser.error('--reuse-baseline-run requires fresh semantic training, --skip-eval-loss and --train-probe-size 0')
    if cli.validation_pairs_per_source < 0:
        parser.error('Validation pair count must be nonnegative')
    if (cli.skip_eval_loss or cli.validation_pairs_per_source) and not cli.fit_check and (cli.mode != 'train' or not cli.semantic_eval):
        parser.error('Fast validation options require --mode train --semantic-eval')
    if cli.validation_pairs_per_source and not cli.pairs_file:
        parser.error('Validation pair subset requires --pairs-file')
    if cli.mode != 'eval' and not cli.train_file:
        parser.error('--train-file is required for train/benchmark')
    if cli.mode == 'eval' and (cli.resume or cli.max_steps is not None):
        parser.error('eval loads --model directly; do not pass --resume or --max-steps')
    if cli.semantic_eval and cli.mode == 'benchmark':
        parser.error('Semantic selection requires train or eval mode, not repeated benchmark data')
    if (not 0 < cli.eval_every_fraction <= 1 or cli.early_stopping_patience < 0
            or cli.generation_max_new_tokens < 1 or cli.train_probe_size < 0
            or (cli.semantic_eval_steps is not None and cli.semantic_eval_steps < 1)):
        parser.error('Invalid semantic evaluation interval, patience or generation/probe size')
    if cli.pairs_file and not cli.semantic_eval:
        parser.error('--pairs-file requires --semantic-eval')
    if cli.keep_checkpoints < 2:
        parser.error('--keep-checkpoints must be at least two to protect best and latest')
    if cli.eval_split != 'validation' and (cli.mode != 'eval' or not cli.semantic_eval):
        parser.error('Held-out test/OOD evaluation requires --mode eval --semantic-eval')
    if cli.baseline_predictions and (cli.mode != 'eval' or not cli.semantic_eval):
        parser.error('--baseline-predictions requires standalone semantic eval')
    return cli


def validate_fit_records(train_rows, eval_rows):
    if not train_rows or train_rows != eval_rows:
        raise ValueError('Fit check requires exactly the same nonempty questions as train-file and eval-file')


def execute_mode(trainer, mode, resume=None, skip_eval_loss=False):
    """Keep evaluation-only dispatch testable without CUDA or Transformers."""
    if mode != 'eval':
        result = trainer.train(resume_from_checkpoint=resume)
        trainer.save_metrics('train', result.metrics)
        trainer.save_state()
    if skip_eval_loss:
        return {}
    metrics = trainer.evaluate()
    trainer.save_metrics('eval', metrics)
    trainer.log_metrics('eval', metrics)
    return metrics


def main():
    cli = parse_args()
    if min(cli.max_length, cli.gradient_accumulation, cli.save_steps, cli.epochs) <= 0:
        raise ValueError('Lengths, accumulation, save interval and epochs must be positive')
    if cli.max_steps is not None and cli.max_steps <= 0:
        raise ValueError('--max-steps must be positive')
    selected_devices = device_tokens(os.environ.get('CUDA_VISIBLE_DEVICES', ''))
    world_size = int(os.environ.get('WORLD_SIZE', '1'))
    if world_size != len(selected_devices) or (cli.expected_world_size is not None
                                              and world_size != cli.expected_world_size):
        raise ValueError('World size must match explicitly selected GPUs; use run_shared.sh')
    output = Path(cli.output_dir).resolve()
    if output.exists() and any(output.iterdir()) and not cli.resume:
        raise ValueError('Use a fresh output directory, or --resume for an existing run')
    if cli.resume and not (Path(cli.resume) / 'trainer_state.json').is_file():
        raise ValueError('--resume must name a complete Trainer checkpoint')

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, Trainer, TrainerCallback, TrainingArguments, set_seed

    if cli.loss_backend == 'liger':
        validate_liger_support()
    loss_options = backend_options(cli.loss_backend)
    ds_config = json.loads(Path(cli.deepspeed).read_text())
    if ds_config['zero_optimization']['stage'] != 3:
        raise ValueError('This entry point requires ZeRO-3')
    if cli.mode == 'eval':
        ds_config.pop('optimizer', None)
        ds_config.pop('scheduler', None)
    # Construct this BEFORE model loading: Transformers initializes parameters under ZeRO-3.
    args = TrainingArguments(
        output_dir=str(output), deepspeed=ds_config, bf16=True, fp16=False,
        per_device_train_batch_size=1, per_device_eval_batch_size=1,
        gradient_accumulation_steps=cli.gradient_accumulation,
        gradient_checkpointing=True, gradient_checkpointing_kwargs={'use_reentrant': False},
        learning_rate=cli.learning_rate, weight_decay=0.0, max_grad_norm=1.0,
        lr_scheduler_type='constant', warmup_steps=0,
        num_train_epochs=cli.epochs,
        max_steps=cli.max_steps if cli.max_steps is not None else (20 if cli.mode == 'benchmark' else -1),
        logging_steps=1, save_strategy='no' if cli.mode == 'eval' else 'steps',
        save_steps=cli.save_steps, save_total_limit=cli.keep_checkpoints,
        eval_strategy='no', prediction_loss_only=True, save_only_model=False,
        report_to=[], dataloader_num_workers=0, remove_unused_columns=False,
        seed=cli.seed, data_seed=cli.seed, ddp_timeout=1800,
        **loss_options,
    )
    if not torch.cuda.is_available():
        raise RuntimeError('CUDA training is required')
    output.mkdir(parents=True, exist_ok=True)
    set_seed(cli.seed)
    tokenizer = AutoTokenizer.from_pretrained(cli.model)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    fingerprint = lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
    train_hash = fingerprint(cli.train_file) if cli.mode != 'eval' else None
    signature = dict(model=cli.model, train_sha256=train_hash,
                     eval_sha256=fingerprint(cli.eval_file), deepspeed=ds_config,
                     template_sha256=hashlib.sha256(tokenizer.chat_template.encode()).hexdigest(),
                     world_size=args.world_size, max_length=cli.max_length, mode=cli.mode,
                     loss_backend=cli.loss_backend, loss_options=loss_options,
                     gradient_accumulation=cli.gradient_accumulation, learning_rate=cli.learning_rate, seed=cli.seed)
    if cli.fit_check:
        signature['fit_check'] = True
    if cli.semantic_eval:
        signature['semantic'] = dict(version=1, eval_every_fraction=cli.eval_every_fraction,
                                     interval=cli.semantic_eval_steps, patience=cli.early_stopping_patience,
                                     max_new_tokens=cli.generation_max_new_tokens, train_probe_size=cli.train_probe_size,
                                     pairs_sha256=fingerprint(cli.pairs_file) if cli.pairs_file else None)
        signature['semantic']['decoding_version'] = 2
        if cli.skip_eval_loss or cli.validation_pairs_per_source:
            signature['semantic'].update(skip_eval_loss=cli.skip_eval_loss,
                                         validation_pairs_per_source=cli.validation_pairs_per_source)
        if cli.checkpoint_policy != 'all-evals' or cli.keep_checkpoints != 2:
            signature['semantic']['checkpoint_policy'] = cli.checkpoint_policy
            signature['semantic']['keep_checkpoints'] = cli.keep_checkpoints
    if cli.resume:
        check_resume(cli.resume, signature)
    train_rows = load_records(cli.train_file) if cli.mode != 'eval' else []
    eval_rows = load_records(cli.eval_file)
    if cli.fit_check:
        validate_fit_records(train_rows, eval_rows)
        if args.process_index == 0:
            print(f'FIT CHECK: {len(train_rows)} fixed questions, {cli.max_steps} updates; '
                  'no validation/generation; same-question fitting only', flush=True)
    else:
        check_split(train_rows, eval_rows)
    if cli.validation_pairs_per_source:
        check_corpus_export(cli.pairs_file)
        full_count = len(eval_rows)
        eval_rows = select_validation_pairs(eval_rows, read_pairs(cli.pairs_file), cli.validation_pairs_per_source)
        if args.process_index == 0:
            print(f'VALIDATION SUBSET: {len(eval_rows)}/{full_count} questions; '
                  f'{cli.validation_pairs_per_source} complete pairs/source', flush=True)
    train_data = [encode_sample(r, tokenizer, cli.max_length) for r in train_rows]
    eval_data = None if cli.fit_check else [encode_sample(r, tokenizer, cli.max_length) for r in eval_rows]
    semantic_callback = None
    if cli.semantic_eval:
        semantic_rows = {cli.eval_split: eval_rows}
        if train_rows and cli.train_probe_size:
            semantic_rows['train_probe'] = select_train_probe(train_rows, cli.train_probe_size)
        semantic_prompts = {split: prepare_prompts(rows, tokenizer, cli.max_length, cli.generation_max_new_tokens)
                            for split, rows in semantic_rows.items()}
        interval = cli.semantic_eval_steps or evaluation_interval(len(train_rows) or 1, world_size,
                                                                  cli.gradient_accumulation, cli.eval_every_fraction)
        if cli.pairs_file:
            check_corpus_export(cli.pairs_file)
        pairs = read_pairs(cli.pairs_file)
        for rows in semantic_rows.values():
            score_records(rows, [], pairs)  # Validate pair sources/history before loading weights.
        semantic_callback = make_semantic_callback(TrainerCallback, cli, semantic_rows, semantic_prompts,
                                                   pairs, interval)
        if args.process_index == 0:
            for split, prompts in semantic_prompts.items():
                write_jsonl(output / f'{split}_generation_prompts.jsonl', prompts)
    # A benchmark uses the same objective but repeats the longest REAL examples.
    # Dynamic padding to 4K then exercises the configured context capacity without fabricating targets.
    if cli.mode == 'benchmark':
        train_data = sorted(train_data, key=lambda r: len(r['input_ids']), reverse=True)[:16]
        train_data = train_data * max(1, (64 + len(train_data) - 1) // len(train_data))
        for row in train_data:
            missing = cli.max_length - len(row['input_ids'])
            if missing:
                for key, value in [('input_ids', tokenizer.pad_token_id), ('attention_mask', 0), ('labels', -100)]:
                    row[key] = row[key] + [value] * missing

    rank = args.process_index
    monitor = ResourceMonitor(output / 'gpu_resources.jsonl') if rank == 0 else None
    if monitor:
        monitor.start()
        atexit.register(monitor.close)
    model = AutoModelForCausalLM.from_pretrained(cli.model, torch_dtype=torch.bfloat16,
                                                attn_implementation='sdpa')
    model.config.use_cache = False
    if cli.loss_backend == 'liger' and model.config.model_type != 'qwen3':
        raise ValueError('This fused CE configuration is validated only for dense Qwen3')
    for parameter in model.parameters():
        parameter.requires_grad_(True)

    class MetricsCallback(TrainerCallback):
        def on_save(self, args, state, control, **kwargs):
            if args.process_index == 0:
                print(f'CHECKPOINT SAVED: {output / f"checkpoint-{state.global_step}"}', flush=True)
            return control

        def on_step_begin(self, args, state, control, **kwargs):
            # Inspect small local shards, never all-gather full parameters for instrumentation.
            self.probes = []
            if cli.mode == 'benchmark':
                for name, parameter in model.named_parameters():
                    shard = getattr(parameter, 'ds_tensor', None)
                    if 'q_proj.weight' in name and shard is not None and shard.numel():
                        self.probes.append((shard, shard.flatten()[:256].detach().cpu().clone()))
            torch.cuda.synchronize()
            torch.cuda.reset_peak_memory_stats()
            self.started = time.perf_counter()

        def on_step_end(self, args, state, control, **kwargs):
            torch.cuda.synchronize()
            row = dict(step=state.global_step, rank=rank, pid=os.getpid(), time=time.time(),
                       step_seconds=time.perf_counter() - self.started,
                       allocated_peak_bytes=torch.cuda.max_memory_allocated(),
                       reserved_peak_bytes=torch.cuda.max_memory_reserved())
            if cli.mode == 'benchmark':
                row['changed_probe_elements'] = sum(
                    int((shard.flatten()[:256].detach().cpu() != before).sum())
                    for shard, before in self.probes)
                row['probe_elements'] = sum(before.numel() for _, before in self.probes)
            status = Path('/proc/self/status')
            if status.exists():
                row['host_process_memory'] = [line for line in status.read_text().splitlines()
                                              if line.startswith(('VmRSS:', 'VmHWM:'))]
            with (output / f'rank_{rank}_steps.jsonl').open('a') as stream:
                stream.write(json.dumps(row) + '\n')
            if control.should_training_stop:
                control.should_save = True
            return control

    class FusedTrainer(FusedLossMixin, Trainer):
        pass

    trainer_class = FusedTrainer if cli.loss_backend == 'liger' else Trainer
    trainer = trainer_class(model=model, args=args, train_dataset=train_data if cli.mode != 'eval' else None,
                      eval_dataset=eval_data,
                      data_collator=ToolCollator(tokenizer.pad_token_id), processing_class=tokenizer,
                      callbacks=[MetricsCallback()] + ([semantic_callback] if semantic_callback else []))
    if semantic_callback:
        semantic_callback.trainer = trainer
    patch = verify_patch(model) if cli.loss_backend == 'liger' else None
    # Trainer has applied the Liger patch; the ZeRO engine is initialized later.
    if patch is not None:
        patch['zero3_external_head'] = register_zero3_fused_head(model)
    if rank == 0:
        manifest = dict(arguments=vars(cli), world_size=args.world_size, deepspeed=ds_config,
                        cuda_visible_devices=os.environ['CUDA_VISIBLE_DEVICES'],
                        loss_backend=cli.loss_backend, loss_options=loss_options, loss_patch=patch,
                        package_versions=package_versions(),
                        resume_signature=signature,
                        train_sha256=train_hash, eval_sha256=fingerprint(cli.eval_file),
                        template_sha256=hashlib.sha256(tokenizer.chat_template.encode()).hexdigest(),
                        train_samples=len(train_rows), eval_samples=len(eval_rows),
                        torch_version=torch.__version__, pid=os.getpid(),
                        benchmark_padding='4K masked padding; real effective context may be shorter',
                        full_parameter_count=sum(getattr(p, 'ds_numel', p.numel()) for p in model.parameters()))
        stamp = time.time_ns()
        (output / f'run_manifest_{stamp}.json').write_text(json.dumps(manifest, indent=2) + '\n')
        if cli.mode != 'eval':
            model.config.save_pretrained(output)
            tokenizer.save_pretrained(output)
    try:
        final_metrics = execute_mode(trainer, cli.mode, cli.resume, skip_eval_loss=cli.skip_eval_loss or cli.fit_check)
        if semantic_callback and cli.mode == 'eval':
            semantic_callback.run(trainer.state, trainer.control, select=False, include_loss=False,
                                  existing_loss_metrics=final_metrics)
    finally:
        if monitor:
            monitor.close()
            atexit.unregister(monitor.close)


if __name__ == '__main__':
    main()
