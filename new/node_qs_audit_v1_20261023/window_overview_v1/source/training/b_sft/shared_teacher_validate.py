"""Revalidate original game structures under the common social teacher."""
from pathlib import Path
from collections import Counter
from copy import deepcopy
import json
import time
from training.b_sft.shared_teacher import SharedGame,IncompatibleHistory,SearchLimit,specification


def validate_game(raw,out,**budgets):
    if out.exists():raise ValueError('Use a new output directory')
    out.mkdir(parents=True);start=time.monotonic();game=SharedGame(raw,**budgets)
    annotated=deepcopy(raw);annotated['teacher_model']=specification(budgets.get('turns',2))
    result=dict(id=raw['id'],fixture=annotated,teacher=specification(budgets.get('turns',2)),budgets=budgets,
        old_history={},episodes=[],training_ready=False)
    try:
        pos=game.replay(raw.get('history',[]));t,index,possible=pos
        result['old_history']=dict(status='compatible',worlds=len(possible))
        if t.entries[index].actor==raw['ego']:
            result['old_history'].update(B=game.belief(pos,raw['ego'],raw['own_preferences']),
                P=t.labels(index,possible,raw['ego'],raw['own_preferences']))
    except IncompatibleHistory as exc:result['old_history']=dict(status='incompatible',reason=str(exc))
    except (SearchLimit,ValueError) as exc:result['old_history']=dict(status='unavailable',reason=str(exc))
    # Enumerate actual worlds for validation only. The solver is built once
    # from the public catalogue and never sees the chosen actual world.
    for i,world in enumerate(game.worlds):
        try:
            episode=game.episode(world);episode['environment_world']=world
            (out/f'episode-{i:03d}.json').write_text(json.dumps(episode,indent=2)+'\n')
            records=episode['records'];ego_records=[r for r in records if r['input']['player']==raw['ego']]
            item=dict(world_index=i,status='terminal',utilities=episode['utilities'],decisions=len(records),ego_decisions=len(ego_records),
                prosocial_ties=sum(r['P']['prosocial_tie_resolved'] for r in records),residual_ties=sum(r['P']['residual_tie'] for r in records),
                path=str(out/f'episode-{i:03d}.json'))
        except (SearchLimit,ValueError) as exc:item=dict(world_index=i,status='unavailable',reason=str(exc))
        result['episodes'].append(item)
        print(json.dumps(dict(id=raw['id'],**item)),flush=True)
    result.update(seconds=round(time.monotonic()-start,3),windows=len(game.windows),
        certificates=[t.certificate for t in game.windows.values()],
        statuses=dict(Counter(x['status'] for x in result['episodes'])))
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--fixture',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--turns',type=int,default=2);p.add_argument('--max-nodes',type=int,default=60000)
    p.add_argument('--max-sweeps',type=int,default=16);p.add_argument('--seconds',type=float,default=30)
    a=p.parse_args();raw=json.loads(a.fixture.read_text())
    validate_game(raw,a.output_dir,turns=a.turns,max_nodes=a.max_nodes,max_sweeps=a.max_sweeps,seconds=a.seconds)
