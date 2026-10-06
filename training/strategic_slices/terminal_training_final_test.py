"""Final-checkpoint test orchestration; importable without the GPU stack."""
import json
from pathlib import Path
from .common import file_hash
from .freeze import atomic_json
from .terminal_training import ensure
from .terminal_training_evaluate import Validator


def run_final_test(pipeline):
    result_path=pipeline.root/'RESULT.json'
    result=json.loads(result_path.read_text())
    def status(value,**details):
        result['final_test']=dict(status=value,**details)
        atomic_json(result_path,result)
    if (result['status']!='complete' or pipeline.stop_requested or
            result['training_response_tokens']<pipeline.options['total_tokens']):
        status('not_run',reason='Training paused, interrupted, or token budget incomplete')
        return
    checkpoint=Path((pipeline.root/'LAST_CHECKPOINT').read_text().strip())
    ensure(checkpoint.name==f'checkpoint-{pipeline.state.step}' and (checkpoint/'COMPLETE.json').is_file(),
        'Final test requires the completed final optimizer checkpoint')
    data=pipeline.collector.dataset;cfg=pipeline.collector.cfg
    identity=dict(version='terminal-final-test-v1',checkpoint=str(checkpoint.resolve()),
        checkpoint_complete_sha256=file_hash(checkpoint/'COMPLETE.json'),dataset_sha256=data.sha,
        split='test',repeats=pipeline.options['test_repeats'],seed=cfg['seed'],
        temperature=0.,max_tokens=cfg['max_tokens'],context=cfg['context'],
        optimizer_step=pipeline.state.step,training_response_tokens=result['training_response_tokens'])
    folder=pipeline.root/'test';folder.mkdir(exist_ok=True)
    marker=folder/'COMPLETE.json';report_path=folder/'report.json'
    if marker.exists():
        done=json.loads(marker.read_text())
        ensure(done['identity']==identity and done['files']=={'report.json':file_hash(report_path)},
            'Completed test identity/report changed')
        status('complete',report=str(report_path),generated_response_tokens=done['generated_response_tokens'])
        return
    status('running',checkpoint=identity['checkpoint'])
    def generate(requests):
        if pipeline.stop_requested:raise InterruptedError('Stop requested during final test')
        outputs=pipeline.generate(requests)
        if pipeline.stop_requested:raise InterruptedError('Stop requested during final test')
        return outputs
    try:
        with pipeline.phase('terminal_test_weight_sync'):
            pipeline.actor_train.offload_states(blocking=True)
            pipeline.model_update(pipeline.state.step+1)
        with pipeline.phase('terminal_final_test'):
            report=Validator(data,generate,cfg,repeats=pipeline.options['test_repeats'],split='test').run()
            if pipeline.stop_requested:raise InterruptedError('Stop requested during final test')
            report.update(final_checkpoint=identity,used_for_checkpoint_selection=False,
                historical_test_exposure='This split appeared in earlier base-model D analysis; not a never-inspected blind test.')
            atomic_json(report_path,report)
            atomic_json(marker,dict(identity=identity,files={'report.json':file_hash(report_path)},
                generated_response_tokens=report['generated_response_tokens']))
            status('complete',report=str(report_path),generated_response_tokens=report['generated_response_tokens'])
    except InterruptedError as exc:
        status('interrupted',error=str(exc),resume_checkpoint=identity['checkpoint'])
    except BaseException as exc:
        status('failed',error=repr(exc),resume_checkpoint=identity['checkpoint'])
        raise
    finally:
        pipeline.actor_infer.offload_states(blocking=True)
