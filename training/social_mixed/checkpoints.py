"""Retain recent complete optimizer states within this run only."""
from pathlib import Path
import json
import shutil

SELECTION_VERSION='development-best-v1'

def selection_score(metrics,arm):
    """Development only; failed games enter SP's conservative cohort bound."""
    if arm in ('outcome','decomposed'):
        return [metrics['bp/P/all/accuracy']]
    if arm in ('bp','b_only','p_only','outcome','decomposed'):
        b=sum(metrics[f'bp/{k}/{mode}/accuracy'] for k in ('B1','B2','B3') for mode in ('binary','linear'))/6
        p=sum(metrics[f'bp/{k}/{mode}/accuracy'] for k in ('P1','P2','P3','P4') for mode in ('binary','linear'))/8
        return [b if arm=='b_only' else p if arm=='p_only' else p if arm in ('outcome','decomposed') else .5*(b+p)]
    if arm=='selfplay':
        return [metrics['games/current_team/all/cohort_player_utility_lower'],
                metrics['games/current_team/all/completion_rate'],
                -metrics['games/current_team/all/invalid_rate']]
    raise ValueError('Best-checkpoint selection supports bp and selfplay only')


def prune(root, keep=2):
    if keep<1:raise ValueError('Keep at least one complete recovery point')
    root=Path(root).resolve()
    completed=[]
    for path in (root/'checkpoints').glob('checkpoint-*'):
        suffix=path.name.removeprefix('checkpoint-')
        if suffix.isdigit() and (path/'COMPLETE.json').is_file():completed.append((int(suffix),path))
    removed=[]
    protected=set()
    # EVALUATED_CHECKPOINTS is an audit ledger, not a retention request. Its
    # entries may point at checkpoints that have since been pruned; protecting
    # every evaluated candidate would retain the whole training trajectory and
    # defeat the bounded-storage contract.
    pointer=root/'BEST_CHECKPOINT'
    if pointer.exists():protected.add(Path(pointer.read_text().strip()).resolve())
    for step,path in sorted(completed,reverse=True)[keep:]:
        if path.resolve() in protected:continue
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
