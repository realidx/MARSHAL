"""The terminal-step collector on the proven ROLL optimizer/sync/checkpoint loop."""
import json
from pathlib import Path
import torch
from training.social_mixed.pipeline import SocialPipeline
from .terminal_training import TrainingData,Collector,ensure
from .terminal_training_evaluate import Validator
from .terminal_training_checkpoints import select_best,retain_checkpoints,finalize_checkpoints,SELECTION


class TerminalPipeline(SocialPipeline):
    @torch.no_grad()
    def run(self):
        # A stopped run may have reached the budget before final validation.
        # On resume, evaluate the restored actor before writing its new snapshot.
        if (self.state.step>=0 and self.state.kv.get('training_response_tokens',0)>=self.options['total_tokens']
                and self.state.kv.get('terminal_last_validation_step')!=self.state.step):
            self.actor_train.offload_states(blocking=True)
            self.model_update(self.state.step+1)
            self.validate(self.state.step,self.state.kv['training_response_tokens'])
        super().run()
        finalize_checkpoints(self)
        from .terminal_training_final_test import run_final_test
        run_final_test(self)

    def save(self,step,force=False):
        best=self.state.kv.get('best_validation')
        if best and best['step']==step:
            # A resumed final/best is copied into this run only once.
            best['checkpoint']=str((self.root/'checkpoints'/f'checkpoint-{step}').resolve())
        super().save(step,force=force)
        retain_checkpoints(self)

    def configure_collection(self,config,options):
        data=TrainingData(options['pool'],options['selection'])
        ensure(data.sha==options['dataset_sha256'],'Training data changed after launch')
        self.collector=Collector(data,self.generate,seed=options['seed'],replicas=options['replicas'],
            concurrency=options['concurrency'],max_tokens=options['max_tokens'],context=options['context'],
            questions_per_update=options['questions_per_update'])
        saved=self.state.kv.get('stable_recipe')
        if saved:self.collector.restore(saved)
        else:ensure(self.state.step<0,'Cannot resume another collector')
        best=self.state.kv.get('best_validation')
        if best:
            ensure(best['selection_version']==SELECTION['version'],'Checkpoint selection rule changed')
            ensure((Path(best['checkpoint'])/'COMPLETE.json').is_file(),'Missing inherited best checkpoint')
        self.validator=Validator(data,self.generate,self.collector.cfg,repeats=options['validation_repeats'],limit=options['validation_limit'])

    @torch.no_grad()
    def validate(self,step,consumed,selection_candidate=True):
        with self.phase('terminal_validation'):
            try:
                report=self.validator.run()
                report['protocol'].update(selection_candidate=bool(step>=0 and selection_candidate),checkpoint_selection=SELECTION)
                report.update(optimizer_step=step,completed_updates=step+1,training_response_tokens=consumed)
                folder=self.root/'validation';folder.mkdir(exist_ok=True)
                (folder/f'step-{step+1}.json').write_text(json.dumps(report)+'\n')
                metrics={'eval/step_binary_accuracy':report['slices']['per_decision_accuracy'],
                    'eval/slice_completion':report['slices']['completion_rate'],
                    'eval/window_success':report['slices']['full_window_success_rate'],
                    'training_response_tokens':consumed,'system/step':step}
                for mode,strata in report['full_games']['metrics'].items():
                    metrics[f'eval/{mode}/completion']=strata['all']['completion_rate']
                    value=strata['all']['player_utility_completed_parent_macro']['mean']
                    if value is not None:metrics[f'eval/{mode}/terminal_utility']=value
                    metrics[f'eval/{mode}/utility_lower']=strata['all']['cohort_player_utility_bounds'][0]
                with (self.root/'metrics.jsonl').open('a') as log:log.write(json.dumps(metrics)+'\n')
                self.state.log_history.append(metrics);self.tracker.log(metrics,step=step+1)
                self.actor_infer.offload_states(blocking=True)
                if selection_candidate:select_best(self,report,step,consumed)
            finally:self.actor_infer.offload_states(blocking=True)
