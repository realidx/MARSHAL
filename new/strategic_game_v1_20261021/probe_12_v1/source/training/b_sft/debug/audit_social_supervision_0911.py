"""Read-only audit of the downloaded run; writes separate diagnostic artifacts.

Run from the repository root. Solver replay checks reproducibility; direct
ALL_OF payoff arithmetic is independent of solver value/goal evaluation code.
Neither check proves robustness to a different partner policy.
"""
from collections import Counter
from pathlib import Path
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from training.b_sft.social_lm_eval import load_pack
from training.b_sft.online_social import OnlineSocial, VERSION
from benac_p.endgame_diagnose import decode_action

PACK = ROOT / 'new/local_data/social_generalization_v2'
RUN = ROOT / 'training/b_sft/debug/social_review_base_430206_0911'
OUT = ROOT / 'training/b_sft/debug/social_supervision_audit_0911'
SELECTED = [
    'evidence-430206-04d00fcfeb5b5917',
    'evidence-430230-aa5dc40b8d935831',
    'evidence-430230-a958415e1ace3856',
    'evidence-430230-713e21944485154d',
    'evidence-430225-371aede394e2fc4c',
    'heldout-four-small-e7580dfa37eaa24c',
    'evidence-430210-67c4eb4178005976',
    'evidence-430230-85ccb0844e7a111d',
]


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def payoff(game, commitments, preferences):
    """Independent binary ALL_OF arithmetic, no native goal/value helpers."""
    contributions = []
    for g in game['goals']:
        assert g.get('binary', True)
        satisfied = all(commitments[a['player_id']][a['action_id']] == 1
                        for a in g['required_actions'])
        contributions.append(dict(goal=g['goal_id'], satisfied=satisfied,
                                  contribution=int(preferences[g['goal_id']]) if satisfied else 0))
    return dict(utility=sum(x['contribution'] for x in contributions), goals=contributions)


def frozen_payoffs(tree, child, world_index, game):
    """Follow fixed policy, then recompute utility without tree.values/payoff."""
    while tree.entries[child].actor is not None:
        entry = tree.entries[child]
        child = entry.children[int(tree.policy[child][world_index])]
    commitments = tree.entries[child].node.state.snapshot_commitments()
    return [payoff(game, commitments, prefs)['utility'] for prefs in tree.worlds[world_index]]


def response_audit(record):
    ctx = record['input']; pending = ctx['pending_offer']
    commitments = ctx['public_state']['commitments']
    accepted = [row[:] for row in commitments]
    accepted[ctx['public_state']['current_proposer']] = pending['proposer_action'][:]
    accepted[pending['partner_id']] = pending['partner_action'][:]
    reject = payoff(ctx['game'], commitments, ctx['own_preferences'])
    accept = payoff(ctx['game'], accepted, ctx['own_preferences'])
    reference = record['P_metrics']['reference']
    if reference['mask']:
        for row in reference['values']:
            actual = accept if row['action']['response'] == 'ACCEPT' else reject
            assert abs(actual['utility'] - row['value']) < 1e-8
    return dict(id=record['id'], reject=reject, accept=accept,
                delta=accept['utility']-reject['utility'], reference_available=reference['mask'])


def inspect(point, record):
    prefix = [e['action'] for e in point['events'] if e['kind'] == 'setup']
    env = OnlineSocial(point['raw'], prefix, turns=2, max_nodes=10000, seconds=20)
    evidence = []
    for event in point['events'][len(prefix):]:
        before = env.belief_table()
        detail = dict(event=event, before_B=before)
        if event['kind'] == 'partner':
            assert env.ensure_teacher(), env.invalid_reason
            tree, index, possible = env.position
            actor = env.actor; observed = event['action']; explanations = []
            for own in dict.fromkeys(tree.worlds[i][actor] for i in possible):
                label = tree.labels(index, possible, actor, own)
                ids = [i for i in possible if tree.worlds[i][actor] == own]
                for ai, value in enumerate(label['actions']):
                    outcomes = [frozen_payoffs(tree, tree.entries[index].children[ai], i,
                                              point['raw']['game']) for i in ids]
                    actual_own = sum(v[actor] for v in outcomes)/len(outcomes)
                    actual_others = sum(sum(v)-v[actor] for v in outcomes)/len(outcomes)
                    assert abs(actual_own-value['own']) < 1e-8
                    assert abs(actual_others-value['others']) < 1e-8
                if observed == label['selected']: reason = 'retained'
                elif observed in label['social_optimal_actions']: reason = 'residual_native_order'
                elif observed in label['own_optimal_actions']: reason = 'prosocial_tie_rule'
                else: reason = 'strict_self_value'
                observed_value = next(a for a in label['actions'] if a['action'] == observed)
                best_own = max(a['own'] for a in label['actions'])
                best_others = max(a['others'] for a in label['actions'] if abs(a['own']-best_own)<1e-8)
                explanations.append(dict(own_type=own,
                    compatible_worlds=sum(tree.worlds[i][actor] == own for i in possible),
                    reason=reason, observed_value=observed_value,
                    best_own=best_own, best_others_among_own_optimal=best_others,
                    selected=label['selected'], all_action_values=label['actions']))
                detail.update(actor=actor, by_type=explanations, window_end=tree.end,
                          game_end=len(point['raw']['game']['round_robin']))
        env.step(event['action'], kind=event['kind'])
        detail.update(after_B=env.belief_table(), actual_event=env.events[-1])
        evidence.append(detail)
    # Preserve the historical model input while adapting its public task wrapper
    # for replay under the new fixed-query interface; game/evidence remain exact.
    from training.b_sft.social_task import fixed_context
    assert env.context() == fixed_context(record['input'])
    assert env.belief_table() == record['teacher_B']
    assert env.fragile == record['fragile_evidence']
    action_values = []
    if record['P_metrics']['reference']['mask']:
        for row in record['P_metrics']['reference']['values']:
            worlds = []
            for world in env.worlds:
                branch = env.fork()
                branch.step(row['action'], kind='learner')
                choice_bases = []
                while not branch.terminal:
                    actor = branch.actor
                    action = branch.reference_action(world[actor])
                    assert not branch.invalid_reason, branch.invalid_reason
                    tree, index, possible = branch.position
                    label = tree.labels(index, possible, actor, world[actor])
                    chosen = next(v for v in label['actions'] if v['action'] == action.to_dict())
                    choice_bases.append(dict(actor=actor, action=action.to_dict(),
                        own_type=world[actor], chosen=chosen,
                        alternatives=label['actions'],
                        prosocial_tie_resolved=label['prosocial_tie_resolved'],
                        residual_tie=label['residual_tie']))
                    branch.step(action, kind='learner' if actor == env.raw['ego'] else 'partner')
                native_payoffs = branch.outcome(world)
                assert not branch.invalid_reason, branch.invalid_reason
                commitments = branch.node.state.snapshot_commitments()
                all_payoffs = [payoff(point['raw']['game'], commitments, prefs) for prefs in world]
                assert [p['utility'] for p in all_payoffs] == native_payoffs
                worlds.append(dict(world=world, own_payoff=all_payoffs[env.raw['ego']],
                    all_utilities=native_payoffs, terminal_commitments=commitments,
                    continuation=branch.events[len(env.events):], choice_bases=choice_bases))
            mean = sum(w['own_payoff']['utility'] for w in worlds)/len(worlds)
            assert abs(mean-row['value']) < 1e-8, (record['id'], row, mean)
            action_values.append(dict(action=row['action'], saved_value=row['value'],
                                      recomputed_value=mean, worlds=worlds))
    return dict(id=record['id'], source=record['source'], facts=record['input'],
        model_B=record['B']['answer'], model_P=record['P']['answer'],
        B_score=record['B_metrics']['score'], teacher_B=env.belief_table(),
        compatible_worlds=env.worlds, fragile=env.fragile,
        evidence=evidence, P_metrics=record['P_metrics'], action_values=action_values)


def main():
    OUT.mkdir(exist_ok=True)
    _, points = load_pack(PACK)
    records = {r['id']: r for r in map(json.loads, (RUN/'decisions.jsonl').read_text().splitlines())}
    response_checks = []; history_categories = Counter()
    for point in points:
        r = records[point['row']['id']]
        reasons = {k for e in point['events'] if e.get('evidence')
                   for k, count in e['evidence']['exclusion_reasons'].items() if count and k != 'retained'}
        history_categories[' + '.join(sorted(reasons)) or 'no_exclusion'] += 1
        if r['input']['pending_offer']:
            ctx = r['input']
            assert len(ctx['game']['round_robin'])-ctx['public_state']['turn_index'] == 1
            response_checks.append(response_audit(r))
    write(OUT/'terminal_responses.json', response_checks)
    audits = []
    for point_id in SELECTED:
        point = next(p for p in points if p['row']['id'] == point_id)
        audit = inspect(point, records[point_id]); audits.append(audit)
        write(OUT/f'{point_id}.json', audit)
        print(json.dumps(dict(id=point_id, evidence_events=len(audit['evidence']),
            P_actions=len(audit['action_values']), fragile=audit['fragile'])), flush=True)
    summary = dict(selected=SELECTED, selected_case_count=len(audits),
        all_terminal_response_count=len(response_checks),
        response_value_comparisons=sum(r['reference_available'] for r in response_checks)*2,
        response_delta_counts=dict(Counter(str(r['delta']) for r in response_checks)),
        point_history_exclusion_categories=dict(history_categories),
        selected_action_values_checked=sum(len(a['action_values']) for a in audits),
        selected_terminal_rollouts_checked=sum(len(v['worlds']) for a in audits for v in a['action_values']),
        source_hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in [RUN/'decisions.jsonl', RUN/'run_config.json', PACK/'checksums.json']},
        limitations=['Selected qualitative cases are not a representative statistical sample.',
            'Policy replay checks the declared solver, not all rational partner explanations.',
            'ALL_OF terminal payoff arithmetic is independently recomputed.',
            'No LM calls, no label mutation, no B-to-P intervention or training implementation.'])
    write(OUT/'summary.json', summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
