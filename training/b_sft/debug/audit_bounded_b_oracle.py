"""Bounded, local-only game audit. No model calls and no training labels export."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from training.b_sft.social_b_oracle import BeliefOracle, VERSION, canonical, forward_fixture
from training.b_sft.social_cases import bundle_fixture
from training.b_sft.shared_teacher import SearchLimit, native
from benac_p.endgame_diagnose import decode_action


def signature(rows):
    return sorted((tuple(row['own_type']), tuple(sorted(canonical(a) for a in row['admissible_actions'])))
                  for row in rows)


def run(out):
    fixtures = [('forward', *forward_fixture(), 1, 2),
                ('deadline', *forward_fixture(deadline=True), 1, 2),
                ('forward_long', *forward_fixture(rounds=2), 1, 2),
                ('bundle', *bundle_fixture(), 1, 0),
                ('bundle_deadline', *bundle_fixture(True), 1, 0)]
    roots, paths, failures = [], [], []
    for name, raw, prefix, target, goal in fixtures:
        for turns in (1, 2, 3):
            for reverse in (False, True):
                o = BeliefOracle(raw, prefix, turns=turns, reverse_actions=reverse)
                try:
                    actor = o.rules.actor(o.node)
                    rows = [o.choices(own) for own in dict.fromkeys(w[actor] for w in o.worlds)]
                    # Compare admissible inverse supports for EVERY root action.
                    supports = {}
                    for action in o.rules.actions(o.node):
                        key = canonical(action.to_dict())
                        allowed = {tuple(row['own_type']) for row in rows
                                   if key in {canonical(a) for a in row['admissible_actions']}}
                        supports[key] = sorted({w[target][goal] for w in o.worlds if w[actor] in allowed})
                    roots.append(dict(case=name, turns=turns, reverse=reverse, rows=rows,
                                      inverse_supports=supports, certificate=o.solve().certificate,
                                      leaf_checks=o.verify_leaf_values()))
                except (SearchLimit, ValueError) as exc:
                    failures.append(dict(case=name, turns=turns, reverse=reverse,
                                         stage='root', error=str(exc)))
            if turns != 2:
                continue
            _, worlds, _ = native(raw)
            # Two deterministic selectors exercise ties; they are not part of B evidence.
            for world in worlds:
                for selector in ('first', 'last'):
                    o = BeliefOracle(raw, prefix, turns=turns)
                    checkpoints = []
                    try:
                        while not o.node.state.is_terminal:
                            if len(checkpoints) > 30:
                                raise ValueError('Audit path bound exceeded')
                            before = o.belief(target, goal)
                            actor = o.rules.actor(o.node)
                            row = o.choices(world[actor])
                            actions = sorted(row['admissible_actions'], key=canonical)
                            action = actions[0 if selector == 'first' else -1]
                            estimate = next(v for v in row['values'] if v['action'] == action)
                            old_worlds = set(o.worlds)
                            o.observe(action)
                            assert world in o.worlds
                            assert set(o.worlds) <= old_worlds
                            after = o.belief(target, goal)
                            checkpoints.append(dict(actor=actor, action=action, before=before, after=after,
                                                    relation='maintain' if before==after else 'update',
                                                    b_evidence=deepcopy(o.events[-1]),
                                                    reference_estimate=estimate,
                                                    terminal_value=row['terminal_value']))
                        inverse = BeliefOracle.replay(raw, o.events, turns=turns)
                        assert inverse.events == o.events
                        assert inverse.worlds == o.worlds
                        r, _, _ = native(raw); node = r.initial()
                        for a in o.history:
                            node = r._apply(node, decode_action(a))
                        assert node.state.is_terminal
                        c = node.state.snapshot_commitments()
                        flags = [all(c[a['player_id']][a['action_id']] == 1 for a in g['required_actions'])
                                 for g in raw['game']['goals']]
                        utilities = [sum(v*flag for v,flag in zip(row, flags)) for row in world]
                        assert c == o.node.state.snapshot_commitments()
                        paths.append(dict(case=name, selector=selector, world=world, history=o.history,
                                          checkpoints=checkpoints, utilities=utilities,
                                          historical_b_replay_verified=True,
                                          terminal=True, final_belief=o.belief(target, goal)))
                    except (SearchLimit, ValueError) as exc:
                        failures.append(dict(case=name, stage='continuation', world=world,
                                             selector=selector, checkpoints=checkpoints, error=str(exc)))
    comparisons = []
    for name, *_ in fixtures:
        by = {(r['turns'], r['reverse']): r for r in roots if r['case']==name}
        for turns in (1,2,3):
            if (turns,False) in by and (turns,True) in by:
                a,b = by[turns,False],by[turns,True]
                comparisons.append(dict(case=name, kind='action_order', turns=turns,
                                        same_actions=signature(a['rows'])==signature(b['rows']),
                                        same_b_support=a['inverse_supports']==b['inverse_supports']))
        for low,high in ((1,2),(2,3)):
            if (low,False) in by and (high,False) in by:
                a,b=by[low,False],by[high,False]
                comparisons.append(dict(case=name, kind='horizon', low=low, high=high,
                                        same_actions=signature(a['rows'])==signature(b['rows']),
                                        same_b_support=a['inverse_supports']==b['inverse_supports']))
    summary = dict(root_checks=len(roots), completed_paths=len(paths), failures=len(failures),
                   leaf_checks=sum(r['leaf_checks'] for r in roots),
                   maintain=sum(c['relation']=='maintain' for p in paths for c in p['checkpoints']),
                   update=sum(c['relation']=='update' for p in paths for c in p['checkpoints']),
                   singleton_paths=sum(len(p['final_belief']['possible_preferences'])==1 for p in paths),
                   historical_b_replays=sum(p['historical_b_replay_verified'] for p in paths),
                   comparisons=comparisons)
    result=dict(version=VERSION, optimizer_updates=0, actual_LM=False, training_ready=False,
                config=dict(horizons=[1,2,3], cutoff='Realized goal utility at end of proposal-turn window',
                            ties='All root lexicographic maximizers; first/last are audit selectors only',
                            replanning='Each action; reference assumes frozen within-window continuation',
                            beliefs='Uniform surviving worlds for decision values; support-only inverse, not posterior',
                            favored='Singleton or undetermined; no invented likelihood ranking'),
                limitations=['Selected finite-window fixed point, not all equilibria.',
                             'Bounded rationality permits later replanning to differ; eventual losses do not invalidate historical action compatibility.',
                             'Five constructed cases, not a balanced corpus or generalization test.',
                             'Matched finite-horizon/reference policy support, not universal preference truth.'],
                fixtures=[dict(name=n,raw=r,prefix=p,target=t,goal=g) for n,r,p,t,g in fixtures],
                roots=roots,paths=paths,failures=failures,summary=summary)
    sources=[Path('training/b_sft')/p for p in ('social_b_oracle.py','shared_teacher.py','social_cases.py')]
    result['source_hashes']={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    out.mkdir(parents=True, exist_ok=False)
    (out/'audit.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(summary,indent=2))


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',type=Path,required=True)
    run(parser.parse_args().out)
