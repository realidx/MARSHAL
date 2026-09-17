"""Information can be unnecessary even with future offers and responses left."""
import argparse
import json
from pathlib import Path

from training.b_sft.build_bp_information import information_tasks
from training.b_sft.shared_teacher import SearchLimit


def candidates():
    for stage in range(3):
        commitments = 2 if stage == 0 else 3
        for count in (2,3,4):
            for partial in (False, True):
                for own_last in (0,1):
                    refs = [dict(player_id=0, action_id=a) for a in range(commitments)]+[dict(player_id=1, action_id=0)]
                    goals = [dict(goal_id=g, binary=True, required_actions=refs) for g in range(count)]
                    if partial and count > 2:
                        goals[-1] = dict(goal_id=count-1, binary=True, required_actions=[dict(player_id=0,action_id=0),dict(player_id=1,action_id=0)])
                    own = [1]*count; own[-1] = own_last
                    rows = [[v]+[1]*(count-1) for v in (1,0,-1)]
                    raw = dict(id=f'information-control-{stage}-{count}-{partial}-{own_last}', ego=0,
                        own_preferences=own, type_catalogues={'0':[own], '1':rows}, history=[],
                        game=dict(n_players=2,n_actions_per_player=[commitments,1],max_changes=1,menu_enabled=False,
                            goals=goals,round_robin=[0,1,0,1] if stage==0 else [1,0,0,1]),
                        pilot_setup=[dict(action='PASS')]*(2 if stage==0 else 1))
                    yield raw, stage


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--out', required=True); a = p.parse_args()
    rows = []; failures = []
    for raw, stage in candidates():
        try:
            tasks, audit = information_tasks(raw, stage)
            if audit['negative']: rows.extend(tasks)
        except (ValueError, SearchLimit) as exc: failures.append(dict(id=raw['id'], reason=str(exc)))
    Path(a.out).write_text(''.join(json.dumps(t)+'\n' for t in rows))
    print(json.dumps(dict(tasks=len(rows), failures=failures)))
