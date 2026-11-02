"""Retention confined to complete checkpoints in the new B/P run directory."""
import json
import os
from pathlib import Path
import shutil


def retain(output_dir, step, metrics):
    root = Path(output_dir).resolve(); folder = root/'checkpoints'
    if step is None or step == 0 or not folder.exists(): return
    current = folder/f'checkpoint-{step-1}'
    if not (current/'COMPLETE.json').is_file():
        raise RuntimeError('Validation model has no matching complete checkpoint')
    pools = {'B': ('formation', 'maintain', 'update'), 'P': ('complete', 'uncertain', 'result_use', 'information')}
    score = sum(sum(metrics[f'{k}/{p}']['accuracy'] for p in ps)/len(ps) for k, ps in pools.items())/2
    index = root/'best_checkpoint.json'
    previous = json.loads(index.read_text()) if index.exists() else None
    controls = ('B/shrink_required','B/fullset_required','B/favored_only_update','P/information_positive','P/information_negative')
    stable = previous is None or all(metrics[k]['accuracy']+.10 >= previous.get('control_accuracy',{}).get(k,0)
                                    for k in controls if k in metrics)
    if previous is None or score > previous['macro_accuracy'] and stable:
        temporary = root/'best_model.tmp'
        if temporary.exists(): raise RuntimeError('Incomplete previous best-model export; inspect before resuming')
        temporary.mkdir()
        for source in current.iterdir():
            if not source.is_file() or source.name == 'COMPLETE.json': continue
            if source.is_symlink(): raise RuntimeError('Checkpoint files must not point outside the run')
            try: os.link(source, temporary/source.name)
            except OSError: shutil.copy2(source, temporary/source.name)
        if not (temporary/'config.json').exists(): raise RuntimeError('Best model lacks model configuration')
        best = root/'best_model'; old = root/'best_model.previous'
        if old.exists(): raise RuntimeError('Stale best-model transaction')
        if best.exists(): best.rename(old)
        temporary.rename(best)
        record = dict(step=step, macro_accuracy=score, source_checkpoint=current.name,
                      control_accuracy={k:metrics[k]['accuracy'] for k in controls if k in metrics})
        tmp = index.with_suffix('.tmp'); tmp.write_text(json.dumps(record, indent=2)+'\n'); tmp.replace(index)
        if old.exists(): shutil.rmtree(old)
    complete = sorted((p for p in folder.glob('checkpoint-*') if p.name.split('-')[-1].isdigit()
                       and not p.is_symlink() and (p/'COMPLETE.json').is_file()), key=lambda p: int(p.name.split('-')[-1]))
    for path in complete[:-2]:
        if path.resolve().parent != folder.resolve(): raise RuntimeError('Retention escaped run directory')
        shutil.rmtree(path)
