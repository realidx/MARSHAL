"""Reproducible local design iteration; writes review artifacts, never training data."""
import argparse
from collections import Counter
from copy import copy, deepcopy
from fractions import Fraction
from itertools import combinations, permutations
import json
import hashlib
from pathlib import Path
import random

import numpy as np

from training.b_sft.catalogues import validate_catalogues
from training.b_sft.shared_teacher import SearchLimit, TOL
from training.b_sft.social_b_oracle import canonical, forward_fixture
from training.b_sft.social_terminal_teacher import TerminalEpisode, Investigate, VERSION
from training.b_sft.social_p_qualitative import (
    terminal_task, proposal_fixture, confidence_fixture, WIDE_ENVELOPES, robust_actions,
)
from training.b_sft.debug.audit_social_semantics import rename, rename_action


def fixture(seed, *, n=3, hidden=1, three_types=False, hidden_goal=0):
    """Small native games: unique ALL_OF requirements and ordinary round rotation."""
    rng = random.Random(seed)
    reqs = list(combinations(range(n), 2)) + [tuple(range(n))]
    rows = [[rng.choice((-1, 0, 1)) for _ in reqs] for _ in range(n)]
    for p in range(n):
        rows[p][p] = 1
    for g in range(len(reqs)):
        if all(row[g] == 0 for row in rows):
            rows[0][g] = 1
    catalogues = {str(p): [rows[p].copy()] for p in range(n)}
    for h in range(hidden):
        p = 1 + h
        g = hidden_goal
        # All candidate profiles keep a positive goal and no goal can become
        # all-neutral in any Cartesian catalogue combination.
        if three_types and all(rows[q][g] == 0 for q in range(n) if q != p):
            rows[0][g] = 1
        catalogues[str(p)] = [rows[p].copy() for _ in range(3 if three_types else 2)]
        for row, v in zip(catalogues[str(p)], (1, 0, -1) if three_types else (1, -1)):
            row[g] = v
    catalogues['0'] = [rows[0].copy()]
    raw = dict(id=f'design-{seed}-p{n}-h{hidden}', ego=0, history=[],
        own_preferences=rows[0], type_catalogues=catalogues,
        game=dict(n_players=n, n_actions_per_player=[1]*n,
            goals=[dict(goal_id=i, binary=True, required_actions=[dict(player_id=p, action_id=0) for p in req])
                   for i, req in enumerate(reqs)],
            round_robin=list(range(n)), max_changes=1, menu_enabled=False))
    validate_catalogues(raw)
    return raw, []


def small_information_fixture():
    raw, prefix = fixture(0)
    raw['id'] = 'investigation-small-positive'
    raw['own_preferences'] = [1, 0, 0, 1]
    raw['type_catalogues'] = {'0': [[1, 0, 0, 1]],
                             '1': [[-1, 1, -1, -1], [1, 1, -1, -1]],
                             '2': [[-1, -1, 1, 0]]}
    return raw, prefix


def choice_information_fixture(seed):
    """Two learner commitments, delayed joint goals and one hidden preference."""
    rng = random.Random(seed)
    reqs = [[(0,a),(p,0)] for a in (0,1) for p in (1,2)]
    reqs += [[(1,0),(2,0)],[(0,0),(1,0),(2,0)],[(0,1),(1,0),(2,0)],[(0,0),(0,1),(1,0),(2,0)]]
    rows = [[rng.choice((-1,0,1)) for _ in reqs] for _ in range(3)]
    for p in range(3):
        rows[p][p] = 1
    for g in range(len(reqs)):
        if all(r[g] == 0 for r in rows):
            rows[0][g] = 1
    catalogues = {str(p):[rows[p].copy()] for p in range(3)}
    hidden_goal = 5 + seed%3
    catalogues['1'] = [rows[1].copy(),rows[1].copy()]
    for r,v in zip(catalogues['1'], (1,-1)):
        r[hidden_goal] = v
    raw = dict(id=f'choice-information-{seed}', ego=0, history=[], own_preferences=rows[0], type_catalogues=catalogues,
        game=dict(n_players=3,n_actions_per_player=[2,1,1],max_changes=1,menu_enabled=False,round_robin=[0,2,1],
            goals=[dict(goal_id=i,binary=True,required_actions=[dict(player_id=p,action_id=a) for p,a in req]) for i,req in enumerate(reqs)]))
    validate_catalogues(raw)
    return raw,[]


def layout_fixture(seed, layout):
    raw, prefix = fixture(seed)
    slots = {'one_hidden': [(1,0)], 'same_player_two': [(1,0),(1,3)],
             'two_players': [(1,0),(2,0)], 'includes_observer': [(1,0),(0,3)]}[layout]
    base = {p:[rows[0].copy()] for p,rows in raw['type_catalogues'].items()}
    for p,g in slots:
        base[str(p)] = [row[:g]+[v]+row[g+1:] for row in base[str(p)] for v in (1,-1)]
    raw['type_catalogues'] = base
    raw['own_preferences'] = base['0'][0]
    raw['id'] += '-'+layout
    validate_catalogues(raw)
    return raw,prefix


def mixed_information_fixture(seed, *, next_learner_turn=False):
    """One delayed hidden goal and another player's hidden immediate goal."""
    raw,prefix=fixture(seed)
    types={p:[rows[0].copy()] for p,rows in raw['type_catalogues'].items()}
    for p,g in ((1,3),(2,0)):
        types[str(p)]=[r[:g]+[v]+r[g+1:] for r in types[str(p)] for v in (1,-1)]
    raw['type_catalogues']=types
    raw['own_preferences']=types['0'][0]
    raw['id']=f'mixed-information-{seed}-'+('next-turn' if next_learner_turn else 'short')
    raw['game']['round_robin']=[0,2,1]
    if next_learner_turn:
        raw['game']['round_robin']=[2,1,0]*2
        prefix=[dict(action='PASS')]*2
    validate_catalogues(raw)
    return raw,prefix


def blind_to_revelation_response(tree, player):
    """Best response to FIXED partners, merging only the revelation outcomes.

    The learner still sees all actions, targets, commitments and timing and can
    infer types from subsequent behavior. Public disclosure to partners remains
    unchanged. This diagnoses use of the revealed answer, not total public VOI.
    """
    groups = {}
    keys = {}
    reach = [None]*len(tree.entries)
    reach[0] = tree.world_weights.copy()
    for i, e in enumerate(tree.entries):
        for ai, child in enumerate(e.children):
            reach[child] = reach[i] if e.actor == player else reach[i]*tree.policy[i][ai]
        if e.actor == player:
            public = deepcopy(e.node.state.public_state())
            for event in public['transcript']:
                if event['action'] == 'INVESTIGATE':
                    event.pop('revealed_preference')
            key = canonical(dict(state=public, pending=None if e.node.pending is None else e.node.pending.to_dict()))
            keys[i] = key
            groups.setdefault(key, []).append(i)
    values = [None]*len(tree.entries)
    policy = list(tree.policy)
    solving = set()

    def value(i):
        if values[i] is not None:
            return values[i]
        e = tree.entries[i]
        if e.actor is None:
            values[i] = e.payoff
        elif e.actor != player:
            values[i] = np.einsum('aw,awp->wp', policy[i], np.array([value(c) for c in e.children]))
        else:
            key = keys[i]
            if key in solving:
                raise AssertionError('Merged learner information sets have imperfect recall')
            solving.add(key)
            indices = groups[key]
            actions = [canonical(a.to_dict()) for a in e.actions]
            for j in indices:
                assert actions == [canonical(a.to_dict()) for a in tree.entries[j].actions]
            av = {j: np.array([value(c) for c in tree.entries[j].children]) for j in indices}
            probs = np.full((len(actions), tree.w), 1/len(actions))
            for ids in tree.groups[player]:
                weights = {j: reach[j][ids] for j in indices}
                total = sum(w.sum() for w in weights.values())
                if not total:
                    weights = {j: tree.world_weights[ids]*tree.possible_masks[j][ids] for j in indices}
                    total = sum(w.sum() for w in weights.values())
                if not total:
                    continue
                means = sum(np.einsum('awp,w->ap', av[j][:, ids], weights[j]) for j in indices)/total
                own = means[:, player]
                other = means.sum(axis=1)-own
                first = np.flatnonzero(own >= own.max()-TOL)
                best = first[other[first] >= other[first].max()-TOL]
                probs[:, ids] = 0
                probs[np.ix_(best, ids)] = 1/len(best)
            for j in indices:
                policy[j] = probs.copy()
                values[j] = np.einsum('aw,awp->wp', probs, av[j])
            solving.remove(key)
        return values[i]

    value(0)
    return values, policy


def investigation_use_audit(episode):
    tree = episode.tree
    actor = tree.entries[0].actor
    blind, _ = blind_to_revelation_response(tree, actor)
    ids = [i for i, w in enumerate(tree.worlds) if w[actor] == tuple(episode.raw['own_preferences'])]
    reports = []
    for a, child in zip(tree.entries[0].actions, tree.entries[0].children):
        if isinstance(a, Investigate):
            full = np.average(tree.values[child][ids], axis=0, weights=tree.world_weights[ids])
            hidden = np.average(blind[child][ids], axis=0, weights=tree.world_weights[ids])
            reports.append(dict(action=a.to_dict(), full=full.tolist(), best_without_reading_result=hidden.tolist(),
                                learner_information_use_gain=float(full[actor]-hidden[actor]),
                                learner_social_information_use_gain=float(full.sum()-full[actor]-hidden.sum()+hidden[actor])))
    return reports


def independent_values(tree):
    """Re-execute every edge and ALL_OF payoff, independent of cached Q arrays."""
    values = [None]*len(tree.entries)
    edges = leaves = 0
    for i in reversed(range(len(tree.entries))):
        e = tree.entries[i]
        if e.actor is None:
            assert e.node.state.is_terminal
            c = e.node.state.snapshot_commitments()
            flags = [all(c[a.player_id][a.action_id] for a in g.required_actions) for g in tree.rules.spec.goals]
            values[i] = np.array([[sum(v*f for v, f in zip(row, flags)) for row in w] for w in tree.worlds], float)
            leaves += 1
        else:
            if e.actor == -1:
                # Its parent owns the INVESTIGATE decision; the chance node
                # records the pre-investigation state and deterministic mask.
                pass
            for a, child in zip(e.actions, e.children):
                actual = tree.entries[child].node
                if e.actor == -1:
                    parent = next(p for p in tree.entries if i in p.children)
                    action = parent.actions[parent.children.index(i)]
                    expected = tree.rules.reveal(e.node, action, a.value)
                elif isinstance(a, Investigate):
                    assert tree.entries[child].actor == -1
                    expected = e.node
                else:
                    expected = tree.rules._apply(e.node, a)
                assert expected.state.public_state() == actual.state.public_state()
                assert expected.pending == actual.pending
                assert expected.worlds == actual.worlds
                edges += 1
            values[i] = sum(tree.policy[i][ai, :, None]*values[c] for ai, c in enumerate(e.children))
        np.testing.assert_allclose(values[i], tree.values[i], atol=1e-9, rtol=0)
    return dict(edges=edges, terminal_leaves=leaves, all_node_values_match=True)


def root_report(episode):
    row = episode.choices(episode.raw['own_preferences'])
    p = row['actor']
    rows = [dict(action=a, own=v[p], others=sum(v)-v[p], probability=prob)
            for a, v, prob in zip(row['actions'], row['values'], row['probabilities'])]
    info = [r for r in rows if r['action'].get('action') == 'INVESTIGATE']
    ordinary = [r for r in rows if r not in info]
    margin = max((r['own'] for r in info), default=float('-inf'))-max(r['own'] for r in ordinary)
    def best_social(rows):
        primary = max(r['own'] for r in rows)
        return max(r['others'] for r in rows if r['own'] >= primary-TOL)
    social_margin = best_social(info)-best_social(ordinary) if info and abs(margin) <= TOL else None
    return dict(rows=rows, investigation_own_margin=margin if info else None,
                investigation_social_margin_on_own_tie=social_margin,
                investigation_strict_advantage=bool(info and (margin > TOL or social_margin is not None and social_margin > TOL)),
                certificate=episode.tree.certificate)


def planning_review_task(episode, tolerance, *, social_tolerance=0.):
    """P-only at an equal-support root; no hidden history inference or numeric belief.

    Arbitrary posteriors and qualitative multi-turn envelopes are not certified
    by this adapter. Such inputs must go through a separate information audit.
    """
    if episode.tree.certificate['diagnostic_policy']:
        raise ValueError('Diagnostic policies cannot supply default-model supervision')
    if episode.events:
        raise ValueError('This review adapter only renders the equal-support root')
    if any(not np.isfinite(t) or t < 0 for t in (tolerance, social_tolerance)):
        raise ValueError('Finite nonnegative regret tolerances required')
    if not np.allclose(episode.weights, episode.weights[0], atol=TOL, rtol=0):
        raise ValueError('Cannot describe unequal posterior weights as equal support')
    row = episode.choices(episode.raw['own_preferences'])
    actor = row['actor']
    values = np.array(row['values'])
    own = values[:, actor]
    social = values.sum(axis=1)-own
    accepted = [i for i, v in enumerate(own) if v >= own.max()-tolerance-TOL
                and all(social[i] >= social[j]-social_tolerance-TOL for j in range(len(own)) if abs(v-own[j]) <= TOL)]
    worlds = [w for w in episode.tree.worlds if w[actor] == tuple(episode.raw['own_preferences'])]
    e = episode.tree.entries[0]
    return dict(source=episode.raw['id'], task='P', training_ready=False,
        input=dict(player=actor, own_preferences=episode.raw['own_preferences'], game=episode.rules.public_game(),
            current_state=e.node.state.public_state(),
            supplied_belief=dict(possible_situations=[[[{1:'want',0:'neutral',-1:'avoid'}[v] for v in r] for r in w] for w in worlds],
                support='The listed situations have equal current support. They are complete joint alternatives.',
                perspective='The catalogue and prior are public. Each player additionally knows their own preferences.'),
            legal_actions=row['actions'], instruction='Use the supplied belief to choose an action and account for future interactions. Prefer higher own goal utility, and benefit others when own utilities tie.'),
        teacher=dict(own_tolerance=tolerance, social_tolerance=social_tolerance, acceptable_actions=[row['actions'][i] for i in accepted],
            action_values=values.tolist(), certificate=episode.tree.certificate,
            scope='Conditional on the audited terminal policy and explicit equal-support belief; not an arbitrary qualitative multi-turn certificate'))


def public_judgment(belief):
    return {k: belief[k] for k in ('possible_preferences', 'favored')}


def belief_examples(episode, player, goal, *, max_per_kind=4, max_history_events=4):
    """Single-query formation and assisted maintenance/update from autonomous edges.

    Exact Fraction likelihoods independently verify all sampled posteriors.
    Setup and environment revelations are never mistaken for behavioral evidence.
    """
    if episode.tree.certificate['diagnostic_policy']:
        raise ValueError('Diagnostic policies cannot supply default-model supervision')
    tasks = []
    counts = Counter()
    observer = episode.raw['ego']
    own = episode.raw['own_preferences']
    start = [Fraction(1, len(episode.tree.worlds)) for _ in episode.tree.worlds]

    def walk(e, exact, old=None, previous_history=None):
        b = e.belief(player, goal, observer=observer, own=own)
        cond = [p if w[observer] == tuple(own) else Fraction(0)
                for p, w in zip(exact, e.tree.worlds)]
        total = sum(cond)
        if not total:
            return
        expected = {name: sum(p for p, w in zip(cond, e.tree.worlds) if w[player][goal] == v)/total
                    for v, name in ((1, 'want'), (0, 'neutral'), (-1, 'avoid'))}
        np.testing.assert_allclose(list(b['preference_weights'].values()), [float(p) for p in expected.values()], atol=1e-9, rtol=0)
        eentry = e.tree.entries[e.index]
        if e.events:
            gold = public_judgment(b)
            formation_key = f"formation-{len(gold['possible_preferences'])}-{'favored' if gold['favored'] != 'undetermined' else 'undetermined'}"
            candidates = [('formation', formation_key)]
            if old is not None:
                change = 'maintain' if gold == old else 'update'
                subtype = 'unchanged' if change == 'maintain' else ('set' if gold['possible_preferences'] != old['possible_preferences'] else 'favored_only')
                candidates.append((change, f'{change}-{subtype}'))
            for kind, key in candidates:
                if counts[key] >= max_per_kind:
                    continue
                counts[key] += 1
                visible = dict(task=kind, observer=observer, own_preferences=own,
                    query=dict(player=player, goal=goal), game=e.rules.public_game(),
                    public_type_catalogues=e.raw['type_catalogues'], initial_setup=e.setup,
                    history=deepcopy(e.events),
                    teacher_rule='Preferences are fixed. Players know their own preferences and public history. They execute the common contingent policy selected by the versioned reference teacher, rather than an unspecified rational policy. Its default procedure starts with uniform choices and updates players synchronously to a stable full-game policy. It maximizes own expected utility, then total others utility on own ties, then samples uniformly on remaining ties. Initial catalogue worlds have equal support. Setup is not evidence.',
                    instruction='Return possible_preferences and favored for the named query.')
                if kind != 'formation':
                    visible.update(previous_belief=old, old_history=previous_history,
                                   new_history=e.events[len(previous_history):])
                tasks.append(dict(source=e.raw['id'], category=key, input=visible,
                                  gold=gold, teacher_only_weights=b['preference_weights'],
                                  label_scope='Conditional on the audited selected teacher; other equilibria need not produce the same answer',
                                  teacher_policy_sha256=e.tree.certificate['policy_sha256'],training_ready=False))
        if len(e.events) >= max_history_events or eentry.actor is None:
            return
        for ai, action in enumerate(eentry.actions):
            # Formation/maintenance/update here focus on behavioral evidence;
            # direct revelations have their own mechanism tests.
            if isinstance(action, Investigate):
                continue
            probs = e.tree.policy[e.index][ai]
            nexact = [p*Fraction(float(q)).limit_denominator(1000000) for p, q in zip(exact, probs)]
            if not sum(nexact) or not any(p for p, w in zip(nexact, e.tree.worlds) if w[observer] == tuple(own)):
                continue
            nexact = [p/sum(nexact) for p in nexact]
            branch = copy(e)
            branch.events = deepcopy(e.events)
            branch.weights = e.weights.copy()
            branch.observe(action.to_dict())
            # An assisted first update starts from the correct catalogue prior.
            # A single informative event is a useful bridge, not a reason to
            # exclude the example for insufficient historical dependence.
            walk(branch, nexact, public_judgment(b), deepcopy(e.events))

    walk(episode, start)
    return tasks


def selection_audit(raw, prefix, base, *, seconds=5, max_nodes=12000):
    """Alternative teacher diagnostics, not gates on the default teacher label."""
    reports = []
    for initialization in ('first', 'last'):
        try:
            e = TerminalEpisode(raw, prefix, seconds=seconds, max_nodes=max_nodes, initialization=initialization)
            different = any(not np.allclose(a, b, atol=1e-9, rtol=0) for a, b in zip(base.tree.policy, e.tree.policy) if a is not None)
            reports.append(dict(initialization=initialization, diagnostic_only=True,
                                affects_default_label_validity=False,
                                status='different_policy' if different else 'same_policy', root=root_report(e)))
        except SearchLimit as exc:
            reports.append(dict(initialization=initialization, diagnostic_only=True,
                                affects_default_label_validity=False,status='solver_failure', detail=str(exc)))
    return reports


def renaming_audit(raw, prefix, base):
    results = []
    n = raw['game']['n_players']
    before = base.choices(raw['own_preferences'])
    for order in permutations(range(n)):
        mapping = dict(enumerate(order))
        rr, pp = rename(raw, prefix, mapping)
        try:
            e = TerminalEpisode(rr, pp, seconds=8, max_nodes=30000)
            after = e.choices(raw['own_preferences'])
            mapped = {}
            for a, v, prob in zip(before['actions'], before['values'], before['probabilities']):
                a = rename_action(a, mapping)
                if a.get('action') == 'INVESTIGATE':
                    a['player'] = mapping[a['player']]
                mapped[canonical(a)] = (v, prob)
            for a, v, prob in zip(after['actions'], after['values'], after['probabilities']):
                old, p = mapped[canonical(a)]
                np.testing.assert_allclose([v[mapping[i]] for i in range(n)], old, atol=1e-9, rtol=0)
                assert abs(prob-p) < 1e-9
            results.append(dict(mapping=mapping, status='same_root_values_and_policy'))
        except SearchLimit as exc:
            results.append(dict(mapping=mapping, status='solver_failure', detail=str(exc)))
    return results


def qualitative_audit(*, social_tolerances=(0.,)):
    reports = []
    for f in (proposal_fixture, confidence_fixture):
        raw, prefix = f()
        for level in ('slightly_likely', 'likely', 'very_likely', 'almost_certain'):
            claims = [dict(event=[dict(player=1, goal=0, value=1)], level=level)]
            for tolerance in (0., .05, .1, .25):
                for social_tolerance in social_tolerances:
                    task = terminal_task(raw, prefix, claims, allow_proposal=f is proposal_fixture,
                                         own_tolerance=tolerance, social_tolerance=social_tolerance, envelopes=WIDE_ENVELOPES)
                    reports.append(dict(source=raw['id'], level=level, own_tolerance=tolerance,
                        social_tolerance=social_tolerance,
                        status=task['teacher']['certificate']['status'], acceptable=task['teacher']['acceptable_actions'], task=task))
    return reports


def run(out, count):
    if out.exists():
        raise ValueError('Use a fresh output directory')
    out.mkdir(parents=True)
    candidates = []
    chosen = []
    tasks = []
    with (out/'mining.jsonl').open('w') as log:
        for seed in range(count):
            raw, prefix = fixture(seed)
            try:
                e = TerminalEpisode(raw, prefix, max_nodes=12000, seconds=5)
                result = root_report(e)
                result.update(source=raw['id'], seed=seed, status='solved')
                margin = result['investigation_own_margin']
                if margin > TOL:
                    candidates.append((margin, raw, prefix))
                if seed < 4:
                    tasks.extend(belief_examples(e, 1, 0, max_per_kind=2))
            except SearchLimit as exc:
                result = dict(source=raw['id'], seed=seed, status='solver_failure', detail=str(exc))
            log.write(json.dumps(result)+'\n')
            log.flush()
            if seed % 10 == 0:
                print(json.dumps(dict(mined=seed+1, positive_candidates=len(candidates))), flush=True)
    raw, prefix = small_information_fixture()
    e = TerminalEpisode(raw, prefix)
    candidates.append((root_report(e)['investigation_own_margin'], raw, prefix))
    for margin, raw, prefix in sorted(candidates, key=lambda x: -x[0])[:3]:
        e = TerminalEpisode(raw, prefix, max_nodes=12000, seconds=8)
        report = dict(raw=raw, prefix=prefix, root=root_report(e), native_replay=independent_values(e.tree),
                      initialization_audit=selection_audit(raw, prefix, e), renaming=renaming_audit(raw, prefix, e),
                      result_use=investigation_use_audit(e))
        payoffs = np.array([e.tree.values[c] for c in e.tree.entries[0].children])
        # Equal catalogue support is the supplied current belief in this audit.
        # One singleton event per world fixes that declared baseline exactly.
        claims = [dict(event=[dict(player=1, goal=0, value=1)], level='equal')]
        report['near_optimal_sensitivity'] = [dict(tolerance=t, certificate=robust_actions(
            payoffs, raw['ego'], e.tree.worlds, claims, own_tolerance=t,
            envelopes={'equal': ((.5, .5),)})) for t in (0., .025, .05, .1)]
        tasks.extend(belief_examples(e, 1, 0))
        chosen.append(report)
    for deadline in (False, True):
        for binary in (False, True):
            raw, prefix = forward_fixture(deadline=deadline)
            if binary:
                raw['type_catalogues']['1'] = [raw['type_catalogues']['1'][i] for i in (0, 2)]
                raw['id'] += '-binary'
            e = TerminalEpisode(raw, prefix)
            tasks.extend(belief_examples(e, 1, 2))
    q = qualitative_audit()
    (out/'investigation_candidates.json').write_text(json.dumps(chosen, indent=2)+'\n')
    (out/'b_review_tasks.jsonl').write_text(''.join(json.dumps(t)+'\n' for t in tasks))
    (out/'p_tolerance_audit.json').write_text(json.dumps(q, indent=2)+'\n')
    summary = dict(version=VERSION, actual_LM=False, training_ready=False, candidates=len(candidates),
        largest_investigation_margin=max((m for m, _, _ in candidates), default=None),
        b_categories=dict(Counter(t['category'] for t in tasks)),
        p_status=dict(Counter(r['status'] for r in q)),
        source_hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (
            Path(__file__),Path('training/b_sft/social_terminal_teacher.py'),Path('training/b_sft/social_p_qualitative.py'))},
        limitations=['Labels describe the selected teacher only; general equilibrium uniqueness is not required',
                     'Investigation advantage alone is not a causal proof of learner information use',
                     'Small review examples, not a balanced or independently held-out training dataset'])
    (out/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--count', type=int, default=60)
    args = parser.parse_args()
    run(args.out, args.count)
