"""Retain recent complete optimizer states within this run only."""
from pathlib import Path
import shutil


def prune(root, keep=2):
    if keep<2:raise ValueError('Keep at least two complete recovery points')
    root=Path(root).resolve()
    completed=[]
    for path in (root/'checkpoints').glob('checkpoint-*'):
        suffix=path.name.removeprefix('checkpoint-')
        if suffix.isdigit() and (path/'COMPLETE.json').is_file():completed.append((int(suffix),path))
    removed=[]
    for step,path in sorted(completed,reverse=True)[keep:]:
        name=path.name
        # Uploader uses hardlinks: delete this run's staging links as well.
        locations=[path,root/'pipeline'/name,root/'actor_train-0'/name,root/'actor_train-1'/name]
        for location in locations:
            if location.exists():
                if location.is_symlink() or root not in location.resolve().parents:
                    raise ValueError('Checkpoint cleanup escaped this run')
                shutil.rmtree(location)
        removed.append(step)
    return removed
