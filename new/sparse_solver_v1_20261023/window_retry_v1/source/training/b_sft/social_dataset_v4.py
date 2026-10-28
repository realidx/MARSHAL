"""Extend v3 with early evidence/planning and balanced terminal controls.

Selection is based on verified teacher properties, never model outputs. Existing
packs and their labels stay frozen. The new pack remains development material.
"""
from collections import defaultdict, Counter
from copy import deepcopy
from pathlib import Path
import argparse
import json

from training.b_sft.social_dataset_v3 import Builder
from training.b_sft.social_holdout_expand import check_pack, read_rows
from training.b_sft.catalogues import validate_catalogues


def informative(row):
    return row['teacher']['B_aux_mask'] and any(
        len(b['answer']['possible_preferences']) < 3 for b in row['teacher']['B_by_target'] or [])


def post_evidence(row):
    q = row['supervision']
    return bool(informative(row) and q['P_basis'] == 'reference_continuation' and q['P_aux_mask'])


def terminal_class(row):
    q = row['supervision']
    return q['response_target'] if q['P_basis'] == 'direct_terminal' else None


def diverse(rows, limit):
    groups = defaultdict(list)
    for row in sorted(rows, key=lambda r: r['id']):
        groups[row['topology']].append(row)
    result = []
    while len(result) < limit and any(groups.values()):
        for group in groups.values():
            if group and len(result) < limit:
                result.append(group.pop(0))
    return result


def select(rows):
    """Cap easy controls globally; reserve priority for informed planning."""
    groups = defaultdict(list)
    for r in rows:
        q = r['supervision']
        if q['P_basis'] == 'reference_continuation' and q['P_aux_mask'] and r['teacher']['B_aux_mask']:
            groups[r['topology']].append(r)
    chosen = []
    for rs in groups.values():
        buckets = defaultdict(list)
        for r in rs:
            q = r['supervision']
            buckets[(post_evidence(r), q['menu_available'], q['phase'])].append(r)
        # Each topology contributes at most 12 planning points; informed points first.
        local = []
        for _ in range(12):
            for k in sorted(buckets, key=lambda k: (not k[0], not k[1], k[2])):
                if len(local) < 12 and buckets[k]:
                    buckets[k].sort(key=lambda r: r['id'])
                    local.append(buckets[k].pop(0))
        chosen.extend(local)
    accept = [r for r in rows if terminal_class(r) == 'accept' and r['teacher']['B_aux_mask']]
    reject = [r for r in rows if terminal_class(r) == 'reject' and r['teacher']['B_aux_mask']]
    count = min(8, len(accept), len(reject))
    chosen += diverse(accept, count) + diverse(reject, count)
    chosen += diverse([r for r in rows if terminal_class(r) == 'menu_choice' and r['teacher']['B_aux_mask']], 2)
    chosen += diverse([r for r in rows if terminal_class(r) == 'tie' and r['teacher']['B_aux_mask']], 2)
    return list({r['id']: r for r in chosen}.values())


def coverage(rows):
    return dict(points=len(rows), post_evidence_planning=sum(post_evidence(r) for r in rows),
                post_evidence_topologies=len({r['topology'] for r in rows if post_evidence(r)}),
                terminal_classes=dict(Counter(terminal_class(r) for r in rows if terminal_class(r))),
                no_evidence_controls=sum(r['supervision']['B_basis'] == 'no_exclusion' for r in rows))


def require_coverage(rows, *, smoke=False):
    c = coverage(rows)
    if c['post_evidence_planning'] < (4 if smoke else 8) or c['post_evidence_topologies'] < 3:
        raise ValueError(f'Missing evidence-followed-by-planning coverage: {c}')
    terminal = c['terminal_classes']
    if terminal.get('accept', 0) < (2 if smoke else 4) or terminal.get('accept') != terminal.get('reject'):
        raise ValueError(f'Terminal ACCEPT/REJECT controls must be balanced: {c}')
    if terminal.get('menu_choice', 0) < 2 or not c['no_evidence_controls']:
        raise ValueError(f'Missing menu/unchanged-prior controls: {c}')
    return c


def terminal_variants(raw):
    """Negative payoff controls on the same native graph, with public setups."""
    ego = raw['ego']
    for goal in raw['game']['goals']:
        req = goal['required_actions']
        if len(req) != 2 or ego not in [a['player_id'] for a in req]:
            continue
        partner = next(a['player_id'] for a in req if a['player_id'] != ego)
        game = deepcopy(raw)
        own = game['own_preferences']
        own[goal['goal_id']] = -1
        if 1 not in own:
            own[next(g for g in range(len(own)) if g != goal['goal_id'])] = 1
        game['type_catalogues'][str(ego)] = [own[:]]
        try:
            validate_catalogues(game)
        except ValueError:
            continue
        order = game['game']['round_robin']
        where = next(i for i in range(len(order)-game['game']['n_players'], len(order)) if order[i] == partner)
        order[where], order[-1] = order[-1], order[where]
        game['id'] += f'-terminal-negative-g{goal["goal_id"]}'
        action = dict(action='OFFER', partner_id=ego,
                      proposer_action=[1], partner_action=[1])
        yield game, [dict(action='PASS') for _ in order[:-1]] + [action]


def menu_fixture(reverse=False):
    # Goal 2 is beneficial; additionally committing player 1 would also activate
    # avoided goal 0. The two menu bundles therefore have different own values.
    own = [1 if reverse else -1, 0, 1]
    reqs = [[(0, 0), (1, 0)], [(1, 0), (2, 0)], [(0, 0), (2, 0)]]
    raw = dict(id='menu-terminal-'+('second' if reverse else 'first'), ego=0,
        own_preferences=own, history=[], type_catalogues={
            '0': [own], '1': [[x, 1, 0] for x in (1, 0, -1)], '2': [[1, 1, -1]]},
        game=dict(n_players=3, n_actions_per_player=[1, 1, 1], max_changes=1,
            round_robin=[1, 2, 0, 0, 2, 1], menu_enabled=True,
            goals=[dict(goal_id=g, binary=True, required_actions=[
                dict(player_id=p, action_id=a) for p, a in req]) for g, req in enumerate(reqs)]))
    options = [dict(partner_id=0, proposer_action=[p], partner_action=[1]) for p in (0, 1)]
    prefix = [dict(action='OFFER', partner_id=2, proposer_action=[0], partner_action=[1]),
              dict(response='ACCEPT')] + [dict(action='PASS') for _ in range(4)]
    prefix.append(dict(action='MENU', partner_id=0, offers=options))
    return raw, prefix


def import_pool(builder, path, *, checked=True):
    if checked: check_pack(path)
    builder.rows.update({r['id']: r for r in read_rows(path/'all_candidates.jsonl')})
    builder.traces.extend(read_rows(path/'trajectories.jsonl'))
    builder.games.update({p.stem: json.loads(p.read_text())['fixture'] for p in (path/'games').glob('*.json')})
    builder.attempts.extend(read_rows(path/'screening.jsonl'))
    builder.roots.extend(t['snapshots'][0] for t in builder.traces if t['snapshots'])


def smoke_rows(rows):
    result = diverse([r for r in rows if post_evidence(r)], 6)
    for kind in ('accept', 'reject', 'menu_choice'):
        result += diverse([r for r in rows if terminal_class(r) == kind and r['teacher']['B_aux_mask']], 2)
    result += diverse([r for r in rows if r['supervision']['B_basis'] == 'no_exclusion'
                      and r['supervision']['P_basis'] == 'reference_continuation'
                      and r['supervision']['P_aux_mask']], 2)
    return list({r['id']: r for r in result}.values())


def build(args):
    builder = Builder(args.output_dir, 'development_generalization')
    import_pool(builder, args.source_pack)
    raws = [deepcopy(raw) for raw in builder.games.values()
            if max(raw['game']['n_actions_per_player']) == 1 and '-menu-' not in raw['id'] and '-response-' not in raw['id']]
    if args.early_pool:
        # Reuse a local candidate build only after finish() independently audits it.
        import_pool(builder, args.early_pool, checked=False)
    else:
        for raw in raws:
            raw = deepcopy(raw); raw['id'] += '-early'
            first = raw['game']['round_robin'].index(raw['ego'])
            builder.add(raw, [dict(action='PASS') for _ in range(first)],
                        'earlier_public_start_all_native_first_actions', all_first_actions=True)
    for raw in raws:
        for game, prefix in terminal_variants(raw):
            builder.add(game, prefix, 'public_terminal_negative_control')
    for reverse in (False, True):
        raw, prefix = menu_fixture(reverse)
        builder.add(raw, prefix, 'public_terminal_menu_control')
    rows = list(builder.rows.values())
    selected = select(rows)
    cov = require_coverage(selected)
    result = builder.finish(selected=selected, version='social-dataset-v4', extra_summary=dict(
        coverage_contract=cov, sampling='Prioritize informed nonterminal planning; balance terminal accept/reject; explicit menu and no-evidence controls.',
        source_pack=str(args.source_pack), scope='Development evaluation, including authored menu controls. No formal unseen-test or causal B-to-P claim.'))
    smoke = Builder(args.smoke_dir, builder.split)
    selected = smoke_rows(rows)
    cov = require_coverage(selected, smoke=True)
    ids = {r['id'] for r in selected}
    sources = {r['source'] for r in selected}
    smoke.rows = {r['id']: r for r in selected}
    smoke.games = {s: builder.games[s] for s in sources}
    smoke.traces = [dict(t, snapshots=[r for r in t['snapshots'] if r in ids])
                    for t in builder.traces if any(r in ids for r in t['snapshots'])]
    smoke.roots = [r['id'] for r in selected]
    smoke.finish(selected=selected, belief_selected=selected, version='social-smoke-v4', extra_summary=dict(
        coverage_contract=cov, sampling='Small stratified verification batch; identical B/P point membership.',
        scope='Development smoke cases with solver labels, not supervised reasoning or a formal test set.'))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-pack', type=Path, default=Path('new/local_data/social_generalization_v3'))
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--smoke-dir', type=Path, required=True)
    parser.add_argument('--early-pool', type=Path)
    print(json.dumps(build(parser.parse_args()), indent=2))


if __name__ == '__main__': main()
