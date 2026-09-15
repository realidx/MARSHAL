"""Callback factory keeps reporting/tests usable without Transformers installed."""

import json
import hashlib
import time
from pathlib import Path

from .generation import generate_predictions, preserve_rng
from .semantic import Selection, score_records, write_json, write_report


def make_semantic_callback(base_class, cli, records, prompts, pairs, interval):
    class SemanticCallback(base_class):
        def __init__(self):
            self.trainer = None
            self.selection = Selection()
            self.root = Path(cli.output_dir).resolve()
            self.baseline = {}
            self.selection_path = self.root / 'selection.json'
            self.eval_split = getattr(cli, 'eval_split', 'validation')
            self.checkpoint_policy = getattr(cli, 'checkpoint_policy', 'all-evals')
            self.reuse_baseline_run = getattr(cli, 'reuse_baseline_run', None)
            baseline_path = getattr(cli, 'baseline_predictions', None)
            if self.reuse_baseline_run:
                previous_root = Path(self.reuse_baseline_run).resolve()
                manifests = sorted(previous_root.glob('run_manifest_*.json'))
                if not manifests:
                    raise ValueError('Baseline reuse requires an original run manifest')
                previous = json.loads(manifests[-1].read_text())
                if previous['arguments']['model'] != cli.model:
                    raise ValueError('Baseline model differs from current starting model')
                if previous['eval_sha256'] != hashlib.sha256(Path(cli.eval_file).read_bytes()).hexdigest():
                    raise ValueError('Baseline evaluation dataset differs')
                baseline_path = previous_root/'semantic'/'step-000000'/self.eval_split/'predictions.jsonl'
            if baseline_path:
                self.baseline[self.eval_split] = [json.loads(line) for line in Path(baseline_path).read_text().splitlines()]
                baseline_ids = [p['id'] for p in self.baseline[self.eval_split]]
                if len(set(baseline_ids)) != len(baseline_ids) or set(baseline_ids) != {r['id'] for r in records[self.eval_split]}:
                    raise ValueError('Baseline predictions must cover exactly the same evaluation split')
                hashes = {p['id']: hashlib.sha256(p['prompt'].encode()).hexdigest() for p in prompts[self.eval_split]}
                decoding = dict(do_sample=False, num_beams=1, max_new_tokens=cli.generation_max_new_tokens,
                                enforced_greedy=True)
                if any(p.get('prompt_sha256') != hashes[p['id']] or p.get('decoding') != decoding
                       for p in self.baseline[self.eval_split]):
                    raise ValueError('Baseline prompt/template/tools or decoding differ; regenerate a matching baseline')
            if cli.resume:
                completed = [p for p in self.root.glob('checkpoint-*')
                             if p.name.split('-')[-1].isdigit() and (p / 'trainer_state.json').is_file()]
                latest = max(completed, key=lambda p: int(p.name.split('-')[-1]), default=None)
                if latest is None or latest.resolve() != Path(cli.resume).resolve():
                    raise ValueError('Semantic resume requires the latest completed checkpoint; do not branch a report history')
                saved = json.loads((Path(cli.resume) / 'semantic_selection.json').read_text())
                self.selection = Selection(**saved['selection'])
                if saved['evaluated_step'] != int(Path(cli.resume).name.split('-')[-1]):
                    # Save-only checkpoints can be newer than the last semantic evaluation.
                    if saved['evaluated_step'] > int(Path(cli.resume).name.split('-')[-1]):
                        raise ValueError('Selection state is newer than resumed weights')
                for split in records:
                    path = self.root / 'semantic' / 'step-000000' / split / 'predictions.jsonl'
                    self.baseline[split] = [json.loads(line) for line in path.read_text().splitlines()]
                if self.selection.best_step:
                    best = self.root / f'checkpoint-{self.selection.best_step}'
                    if not (best / 'trainer_state.json').is_file():
                        raise ValueError('Resume requires the protected best checkpoint')

        def document(self):
            return dict(selection=self.selection.to_dict(), evaluated_step=self.selection.last_step,
                        metric='validation.source_macro_exact', tie_break='earlier step',
                        selected_model=cli.model if self.selection.best_step == 0 else
                        str(self.root / f'checkpoint-{self.selection.best_step}'),
                        selected_original=self.selection.best_step == 0,
                        patience=cli.early_stopping_patience, interval_steps=interval,
                        checkpoint_policy=self.checkpoint_policy)

        def run(self, state, control, *, select=True, include_loss=True, existing_loss_metrics=None):
            trainer = self.trainer
            started = time.perf_counter()
            model = trainer.model
            was_training = model.training
            pending_train_log = getattr(control, 'should_log', None)
            try:
                with preserve_rng():
                    include_loss = include_loss and not getattr(cli, 'skip_eval_loss', False)
                    if trainer.is_world_process_zero():
                        print(f'EVAL step={state.global_step}: loss={include_loss}; '
                              f'generation questions={sum(len(x) for x in records.values())}', flush=True)
                    loss_metrics = trainer.evaluate() if include_loss else (existing_loss_metrics or {})
                    metrics = {}
                    for split, examples in records.items():
                        if trainer.is_world_process_zero():
                            print(f'EVAL GENERATION START: {split}, {len(examples)} questions', flush=True)
                        reused = bool(self.reuse_baseline_run and state.global_step == 0)
                        if reused:
                            predictions = self.baseline[split]
                            if trainer.is_world_process_zero():
                                print(f'REUSED BASELINE: {len(predictions)} predictions; no GPU generation', flush=True)
                        else:
                            predictions = generate_predictions(trainer, prompts[split], trainer.processing_class,
                                                               cli.generation_max_new_tokens, cli.loss_backend)
                        metadata = dict(step=state.global_step, epoch=state.epoch, split=split,
                                        do_sample=False, num_beams=1, max_new_tokens=cli.generation_max_new_tokens,
                                        first_answer_only=True,
                                        reasoning_allowed=all(p.get('allow_preface', True) for p in prompts[split]),
                                        selection_eligible=split == 'validation' and select,
                                        loss_metrics=loss_metrics if split == self.eval_split else {})
                        if reused:
                            metadata['reused_baseline_run'] = str(Path(self.reuse_baseline_run).resolve())
                        # All ranks compute the same decision; rank zero writes only.
                        baseline = self.baseline.get(split, [])
                        metrics[split] = score_records(examples, predictions, pairs, baseline)[0]
                        if trainer.is_world_process_zero():
                            directory = self.root / 'semantic' / f'step-{state.global_step:06d}' / split
                            write_report(directory, examples, predictions, pairs, baseline, metadata)
                        if state.global_step == 0:
                            self.baseline[split] = predictions
            finally:
                model.train(was_training)
                # Nested evaluate() logs clear Trainer's pending optimizer-step
                # log flag. Restore it so eval steps do not disappear from train loss logs.
                if pending_train_log is not None:
                    control.should_log = pending_train_log
            if select:
                improved, stop = self.selection.observe(state.global_step,
                                                       metrics['validation']['source_macro_exact'],
                                                       cli.early_stopping_patience)
                if improved:
                    # Trainer's checkpoint rotation preserves this path, with the newest checkpoint.
                    state.best_metric = self.selection.best_score
                    state.best_global_step = state.global_step
                    state.best_model_checkpoint = (str(self.root / f'checkpoint-{state.global_step}')
                                                   if state.global_step else None)
                if state.global_step and (self.checkpoint_policy == 'all-evals' or improved or stop
                                          or state.global_step >= state.max_steps):
                    control.should_save = True
                if stop:
                    control.should_training_stop = True
            if trainer.is_world_process_zero():
                if select:
                    write_json(self.selection_path, self.document())
                curve = dict(step=state.global_step, epoch=state.epoch,
                             evaluation_split=self.eval_split,
                             nominal_seen_samples=state.global_step * trainer.args.world_size * cli.gradient_accumulation,
                             semantic_seconds=time.perf_counter()-started, loss_metrics=loss_metrics,
                             metrics=metrics, selection=self.document() if select else None)
                with (self.root / 'semantic_curve.jsonl').open('a') as stream:
                    stream.write(json.dumps(curve) + '\n')
                validation = metrics[self.eval_split]
                print(json.dumps(dict(step=state.global_step, source_macro_exact=validation['source_macro_exact'],
                                      overall=validation['overall'], pairs=validation['pairs'],
                                      shortcut_diagnostics=validation['shortcut_diagnostics'],
                                      selected=self.document() if select else None), ensure_ascii=False), flush=True)
            return control

        def on_train_begin(self, args, state, control, **kwargs):
            if not cli.resume:
                return self.run(state, control)
            # Do not spend another update after resuming an already early-stopped run.
            if cli.early_stopping_patience and self.selection.bad_evaluations >= cli.early_stopping_patience:
                raise ValueError('This run already reached early stopping; start a new experiment')
            return control

        def on_step_end(self, args, state, control, **kwargs):
            if state.global_step % interval == 0 or state.global_step >= state.max_steps:
                return self.run(state, control)
            return control

        def on_save(self, args, state, control, **kwargs):
            if self.trainer.is_world_process_zero():
                checkpoint = self.root / f'checkpoint-{state.global_step}'
                write_json(checkpoint / 'semantic_selection.json', self.document())
            return control

    return SemanticCallback()
