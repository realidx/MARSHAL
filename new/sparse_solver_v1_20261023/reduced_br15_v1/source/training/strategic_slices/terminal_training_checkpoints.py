"""Validation-only best selection and best/latest (then best/final) retention."""
import json
import math
from pathlib import Path
from training.social_mixed.checkpoints import prune
from .freeze import atomic_json
from .terminal_training import ensure

SELECTION=dict(version='terminal-validation-window-success-v1',
    metric='validation full_window_success_rate',tie_break='Prefer the later evaluated update, including final.',
    baseline_eligible=False,test_used=False)


def retain_checkpoints(pipeline):
    root=pipeline.root.resolve()
    completed=[p for p in (root/'checkpoints').glob('checkpoint-*')
        if p.name.removeprefix('checkpoint-').isdigit() and (p/'COMPLETE.json').is_file()]
    if not completed:return
    latest=max(completed,key=lambda p:int(p.name.removeprefix('checkpoint-')))
    best=pipeline.state.kv.get('best_validation')
    best_path=None
    if best:
        best_path=Path(best['checkpoint']).resolve()
        ensure((best_path/'COMPLETE.json').is_file(),'Best checkpoint is missing or incomplete')
        (root/'BEST_CHECKPOINT').write_text(str(best_path)+'\n')
        atomic_json(root/'BEST_VALIDATION.json',best)
    # An inherited best stays in the earlier run. Never delete that run's files.
    keep=2 if best_path in completed and best_path!=latest else 1
    removed=prune(root,keep)
    if removed:
        with (root/'checkpoint_retention.jsonl').open('a') as f:
            f.write(json.dumps(dict(policy='best-and-latest-deduplicated',removed=removed))+'\n')


def select_best(pipeline,report,step,consumed):
    if step<0:return
    ensure(report['protocol']['split']=='validation','Best selection must use validation, never test')
    score=float(report['slices']['full_window_success_rate'])
    ensure(math.isfinite(score) and 0<=score<=1,'Invalid validation window success rate')
    pipeline.state.kv['terminal_last_validation_step']=step
    previous=pipeline.state.kv.get('best_validation')
    if previous:
        ensure(previous['selection_version']==SELECTION['version'],'Best selection rule changed on resume')
    if previous is None or [score]>previous['score'] or ([score]==previous['score'] and step>=previous['step']):
        checkpoint=pipeline.root/'checkpoints'/f'checkpoint-{step}'
        best=dict(score=[score],step=step,completed_updates=step+1,training_response_tokens=consumed,
            selection_version=SELECTION['version'],selection=SELECTION,
            checkpoint=str(checkpoint.resolve()),checkpoint_retained=True)
        pipeline.state.kv['best_validation']=best
        # Include the new best metadata in the native optimizer checkpoint.
        pipeline.save(step,force=True)
        retain_checkpoints(pipeline)


def finalize_checkpoints(pipeline):
    result_path=pipeline.root/'RESULT.json'
    result=json.loads(result_path.read_text())
    if result['status']!='complete':return
    final=Path((pipeline.root/'LAST_CHECKPOINT').read_text().strip()).resolve()
    best=pipeline.state.kv.get('best_validation')
    ensure(best is not None and pipeline.state.kv.get('terminal_last_validation_step')==pipeline.state.step,
        'Final checkpoint must be evaluated before finalizing best/final retention')
    retain_checkpoints(pipeline)
    ensure((final/'COMPLETE.json').is_file(),'Missing completed final checkpoint')
    (pipeline.root/'FINAL_CHECKPOINT').write_text(str(final)+'\n')
    record=dict(best=best['checkpoint'],final=str(final),
        unique_checkpoints=len({str(Path(best['checkpoint']).resolve()),str(final)}),selection=SELECTION)
    atomic_json(pipeline.root/'CHECKPOINTS.json',record)
    result['checkpoints']=record;atomic_json(result_path,result)
