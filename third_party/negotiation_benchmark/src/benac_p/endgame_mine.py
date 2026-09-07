"""Export legal native endgame candidates; never certify a research claim by seed.

Uses the existing generator and round-robin schedule. This is a candidate miner,
not the final B/P diagnostic selection procedure. Prefixes include active oracle
proposals and responses; learner prefix actions are seeded legal interventions.
"""
import argparse
import json
import numpy as np
from itertools import combinations, product
from pathlib import Path

from benac_p.generator import GeneratorConfig, generate_game
from benac_p.endgame import Endgame, PartnerDecision, SearchLimit
from benac_p.endgame_partner import RationalPartner, InformationStateRequired
from benac_p.endgame_diagnose import Fixture
from benac_p.diagnose_suite import dump
from dataclasses import replace


def candidates(seed, max_nodes=2000, actions_per_player=1, n_goals=4, n_rounds=2, unknown_goals=1, on_rejection=None, max_remaining_turns=3):
    spec=replace(generate_game(seed,GeneratorConfig(n_players=3,actions_per_player=actions_per_player,n_goals=n_goals,n_rounds=n_rounds)),menu_enabled=True)
    ego=seed % spec.n_players
    target=[p for p in range(spec.n_players) if p!=ego][(seed//spec.n_players)%2]
    # Keep every type valid under the original generator's preference validity
    # constraints; no correlation between different players is introduced.
    eligible=[g.goal_id for g in spec.goals if any(a.player_id==target for a in g.required_actions)]
    for goals in combinations(eligible,unknown_goals):
        goal=goals[0]
        rows=[tuple(map(int,row)) for row in spec.private_preferences]
        if not any(v==1 for j,v in enumerate(rows[target]) if j not in goals):continue
        if any(all(rows[p][g]==0 for p in range(spec.n_players) if p!=target) for g in goals):continue
        types={p:(row,) for p,row in enumerate(rows)}
        types[target]=tuple(tuple(dict(zip(goals,vs)).get(j,old) for j,old in enumerate(rows[target])) for vs in product((1,0,-1),repeat=len(goals)))
        try:
            partner=RationalPartner(spec,types,ego,max_nodes)
            search=Endgame(spec,ego,rows[ego],{p:r for p,r in types.items() if p!=ego},partner,max_nodes=max_nodes)
            world=tuple(rows);node=search.initial();prefix=[];index=0
            while not node.state.is_terminal:
                actor=search.actor(node)
                if actor==ego:
                    if len(spec.round_robin)-node.state.turn_index<=max_remaining_turns:
                        raw=dict(id=f'native-{seed}-g{"_".join(map(str,goals))}-d{index}',ego=ego,game=spec.to_dict(include_private=False),
                            type_catalogues={str(p):[list(row) for row in rs] for p,rs in types.items()},
                            own_preferences=list(rows[ego]),query=dict(player=target,goals=list(goals)),
                            history=[a.to_dict() for a in prefix],source=dict(generator='benac_p.generator.generate_game',seed=seed,
                                scope='Conditional position with all nonqueried preference entries supplied. No additional action/turn restrictions.'))
                        # Replay independently: catches pending-offer and transcript
                        # omissions before an alleged fixed history is exported.
                        check=Fixture(raw,max_nodes)
                        assert check.root.state.snapshot_commitments()==node.state.snapshot_commitments()
                        yield raw
                    decision=PartnerDecision(ego,node.state.public_state(),rows[ego],search.actions(node),None if node.pending is None else node.pending.to_dict())
                    action=decision.legal_actions[int(np.random.default_rng(seed+index*701+goal*97).integers(len(decision.legal_actions)))];index+=1
                else:
                    action=search._partner_action(node,world)
                    node.worlds=tuple(w for w in node.worlds if search._partner_action(node,w)==action)
                prefix.append(action);node=search._apply(node,action)
        except (SearchLimit,InformationStateRequired) as exc:
            if on_rejection is not None:on_rejection(dict(seed=seed,goals=list(goals),reason=str(exc)))
            continue


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--seed',type=int,default=30000)
    p.add_argument('--actions-per-player',type=int,default=1);p.add_argument('--n-goals',type=int,default=4);p.add_argument('--rounds',type=int,default=2);p.add_argument('--unknown-goals',type=int,choices=(1,2),default=1)
    p.add_argument('--seeds',type=int,default=8);p.add_argument('--max-nodes',type=int,default=2000)
    args=p.parse_args(argv)
    if min(args.seeds,args.max_nodes)<1:p.error('Budgets must be positive.')
    fixtures=[];failures=[]
    for seed in range(args.seed,args.seed+args.seeds):
        try:fixtures.extend(candidates(seed,args.max_nodes,args.actions_per_player,args.n_goals,args.rounds,args.unknown_goals,failures.append))
        except (SearchLimit,InformationStateRequired) as exc:failures.append(dict(seed=seed,reason=str(exc)))
        # A failed exact solve is recorded, never converted to a heuristic label.
        dump(args.output,dict(version='native-candidates-v1',purpose='Legal candidates only; not a selected diagnostic dataset.',fixtures=fixtures,search_failures=failures))
        print(f'Seed {seed}: {len(fixtures)} cumulative candidates; {len(failures)} budget exclusions',flush=True)
    if not fixtures:p.exit(2,'No candidates found within this budget. No model measurement was attempted.\n')


if __name__=='__main__':main()
