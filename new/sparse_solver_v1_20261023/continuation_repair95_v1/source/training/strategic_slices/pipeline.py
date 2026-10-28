"""Reuse the production optimizer/sync/checkpoint loop with an isolated corpus."""
import json
from pathlib import Path

import torch
from training.social_mixed.pipeline import SocialPipeline
from .common import Dataset
from .runtime import Collector
from .evaluate import Evaluator


class SlicePipeline(SocialPipeline):
    def configure_collection(self, config, options):
        dataset = Dataset(options['data'])
        if dataset.sha != options['dataset_sha256']:
            raise ValueError('Data changed between launch and initialization')
        self.collector = Collector(dataset, self.generate, options['arm'], seed=config.seed,
                                   replicas=options['replicas'], concurrency=options['concurrency'])
        saved = self.state.kv.get('stable_recipe')
        if saved:
            self.collector.restore(saved)
        elif self.state.step >= 0:
            raise ValueError('Cannot resume a different collector')
        self.validator = Evaluator(dataset, self.generate, repeats=options['validation_repeats'],
                                   seed=config.seed, concurrency=options['concurrency'])

    @torch.no_grad()
    def validate(self, step, consumed, selection_candidate=True):
        # Validation draws learning curves; the predefined final checkpoint is primary.
        with self.phase('validation'):
            report = self.validator.run()
            report.update(optimizer_step=step, completed_updates=step + 1, training_response_tokens=consumed,
                          selection_candidate=False)
            folder = self.root / 'validation'; folder.mkdir(exist_ok=True)
            path = folder / f'step-{step + 1}.json'
            path.write_text(json.dumps(report) + '\n')
            flat = {'eval/completed_updates': step + 1, 'system/step': step,
                    'training_response_tokens': consumed}
            for mode, strata in report['metrics'].items():
                for name, values in strata.items():
                    prefix = f'eval/{mode}/{name}/'
                    flat[prefix + 'completion_rate'] = values['completion_rate']
                    value = values['player_utility_completed_parent_macro']['mean']
                    if value is not None:
                        flat[prefix + 'player_utility'] = value
                    flat[prefix + 'cohort_player_utility_lower'] = values['cohort_player_utility_bounds'][0]
            with (self.root / 'metrics.jsonl').open('a') as log:
                log.write(json.dumps(flat) + '\n')
            self.state.log_history.append(flat)
            self.tracker.log(flat, step=step + 1)
            self.actor_infer.offload_states(blocking=True)
            (self.root / 'parent_exposure.json').write_text(json.dumps(self.collector.state['exposure'], indent=2) + '\n')
