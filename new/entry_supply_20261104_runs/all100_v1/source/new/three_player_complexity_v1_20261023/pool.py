"""Freeze paired complexity arms using geometry/visibility only, before solve."""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
from itertools import product
from pathlib import Path

from .common import parents,snapshot,write,sha,stable
from new.strategic_game_v1_20261021.rules import StrategicRules,VERSION as GAME_VERSION
from new.game_design_feasibility_20261021.design import count_public_tree

ARMS=('H2','H3','A2H2')


def variant(parent,arm):
    assert parent['configuration']['players']==3 and arm in ARMS
    raw=deepcopy(parent['raw']);ng=len(raw['game']['goals'])
    supports=[[sorted({r[g] for r in raw['type_catalogues'][str(p)]}) for g in range(ng)] for p in range(3)]
    hidden=[(p,g) for p in range(3) for g in range(ng) if len(supports[p][g])>1]
    assert len(hidden)==1
    changed=[];target=3 if arm=='H3' else 2
    while len(hidden)<target:
        # Visibility only: no preference values, Q/S, solver outcome or model.
        holders={p for p,g in hidden}
        candidates=[(p,g) for p in range(3) if p not in holders for g in range(ng) if len(supports[p][g])==1]
        p,g=candidates[0];supports[p][g]=[-1,0,1];hidden.append((p,g));changed.append((p,g))
    raw['type_catalogues']={str(p):[list(row) for row in product(*supports[p])] for p in range(3)}
    change_action=None
    if arm=='A2H2':
        goals=raw['game']['goals']
        occurrences={p:[g for g,goal in enumerate(goals) if any(a['player_id']==p for a in goal['required_actions'])] for p in range(3)}
        eligible=[p for p in range(3) if len(occurrences[p])>=2]
        assert eligible
        p=eligible[parent['index']%len(eligible)]
        g=occurrences[p][(parent['index']//len(eligible))%len(occurrences[p])]
        raw['game']['n_actions_per_player'][p]=2
        for a in goals[g]['required_actions']:
            if a['player_id']==p:a['action_id']=1
        change_action=dict(player=p,goal=g,old_action=0,new_action=1)
    rules=StrategicRules(raw)
    used={(a.player_id,a.action_id) for goal in rules.spec.goals for a in goal.required_actions}
    expected={(p,a) for p,k in enumerate(rules.spec.n_actions_per_player) for a in range(k)}
    assert used==expected
    assert all(len({a.player_id for a in g.required_actions})>=2 for g in rules.spec.goals)
    return raw,dict(added_hidden_cells=changed,all_hidden_cells=sorted(hidden),action_change=change_action)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    snapshot(args.output,dict(operation='Freeze99 paired three-player variants and exact structural counts',
        arms=list(ARMS),games_per_arm=33,rounds=2,query_budget=1,offer_budget=1,
        visibility='one additional hidden per previously public-type player in lexicographic order',
        action_rule='one goal occurrence switches to new action of a geometry-eligible player selected by original index',
        admission='No metric, preference value or solve-success filtering; not a production replacement'))
    rows=[]
    for arm in ARMS:
        for parent in parents():
            if parent['configuration']['players']!=3:continue
            raw,changes=variant(parent,arm);rules=StrategicRules(raw);counts=count_public_tree(rules)
            sid=hashlib.sha256(stable(dict(game_version=GAME_VERSION,raw=raw)).encode()).hexdigest()[:24]
            rows.append(dict(index=len(rows),id=sid,original_index=parent['index'],original_parent_id=parent['id'],
                arm=arm,raw=raw,changes=changes,preflight=counts,
                source_selection='All original33 three-player games; no outcome-based inclusion',
                solver='NOT_RUN',Q_S_D='NOT_MEASURED'))
    path=args.output/'games.jsonl';path.write_text(''.join(stable(r)+'\n' for r in rows))
    summary={}
    for arm in ARMS:
        group=[r for r in rows if r['arm']==arm]
        summary[arm]=dict(games=len(group),worlds=sorted({r['preflight']['worlds'] for r in group}),
            public_nodes_min=min(r['preflight']['public_histories'] for r in group),
            public_nodes_max=max(r['preflight']['public_histories'] for r in group),
            node_world_pairs_max=max(r['preflight']['node_world_pairs'] for r in group),
            action_counts=dict(Counter(stable(r['raw']['game']['n_actions_per_player']) for r in group)))
    write(args.output/'MANIFEST.json',dict(version='three-player-paired-complexity-pool-v1',games=len(rows),
        games_sha256=sha(path),summary=summary,production_pool_changed=False,model='NOT_USED',
        pilot_original_indices=[3,7],full_solver='NOT_RUN',new_D='NOT_MEASURED'))
    write(args.output/'COMPLETE.json',dict(games=len(rows),manifest_sha256=sha(args.output/'MANIFEST.json'),
        pipeline_snapshot_sha256=sha(args.output/'pipeline_snapshot.json')))
    print(summary)


if __name__=='__main__':main()
