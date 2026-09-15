"""Local audit of frozen readable tasks; never rewrites labels or trains.

Reconstruct prior support from player-visible public facts and generation rules.
The independent backward check uses native action trees but neither the selected
policy nor its values. It is applicable only when its per-world choices are
identical within every actual information set (otherwise it would leak truth).
"""
import argparse
from collections import Counter, defaultdict
from copy import copy
from itertools import product
import json
from pathlib import Path

import numpy as np

from training.b_sft.social_private_teacher import PrivateEpisode, audit_native, observed_slots
from training.b_sft.social_bp_curriculum import acceptable
from training.b_sft.social_p_qualitative import robust_actions

VALUES = {'want': 1, 'neutral': 0, 'avoid': -1}


def read(path):
    return [json.loads(s) for s in Path(path).read_text().splitlines() if s.strip()]


def reconstruct(inp):
    game = inp['game']; n = game['n_players']; g = len(game['goals'])
    public = {(x['player'], x['goal']): VALUES[x['preference']] for x in inp['public_preferences']}
    slots = [(p, q) for p in range(n) for q in range(g) if (p, q) not in public]
    worlds = []
    for vs in product((1, 0, -1), repeat=len(slots)):
        prefs = {**public, **dict(zip(slots, vs))}
        w = tuple(tuple(prefs[p, q] for q in range(g)) for p in range(n))
        if any(1 not in row for row in w): continue
        if any(all(w[p][q] == 0 for p in range(n)) for q in range(g)): continue
        worlds.append(w)
    rows = {str(p): list(dict.fromkeys(w[p] for w in worlds)) for p in range(n)}
    assert set(product(*(rows[str(p)] for p in range(n)))) == set(worlds), 'Unsupported correlation'
    own = tuple(VALUES[inp['own_preferences'][f'goal_{q}']] for q in range(g))
    return dict(game=game, ego=inp['observer'], own_preferences=list(own),
                type_catalogues={p: [list(r) for r in rs] for p, rs in rows.items()}, history=[]), own


def independent_backward(tree):
    """Perfect-world induction, then strict no-extra-information check."""
    values = [None] * len(tree.entries); policies = {}
    for i in reversed(range(len(tree.entries))):
        e = tree.entries[i]
        if e.actor is None:
            c = e.node.state.snapshot_commitments()
            done = [all(c[a.player_id][a.action_id] for a in g.required_actions) for g in tree.rules.spec.goals]
            values[i] = np.array([[sum(v * d for v, d in zip(row, done)) for row in w] for w in tree.worlds], float)
            continue
        av = np.array([values[c] for c in e.children])
        own = av[:, :, e.actor]; social = av.sum(axis=2) - own
        best = own >= own.max(axis=0) - 1e-9
        best &= social >= np.where(best, social, -np.inf).max(axis=0) - 1e-9
        policy = best / best.sum(axis=0)
        policies[i] = policy
        values[i] = np.einsum('aw,awp->wp', policy, av)
    applicable = all(np.allclose(policies[i][:, ids], policies[i][:, ids[:1]], atol=1e-9, rtol=0)
                     for i, groups in tree.information_groups.items() for ids in groups)
    if applicable:
        for i, policy in policies.items():
            np.testing.assert_allclose(policy, tree.policy[i], atol=1e-9, rtol=0)
        for i, value in enumerate(values):
            np.testing.assert_allclose(value, tree.values[i], atol=1e-9, rtol=0)
    return applicable


def independent_final_actions(episode):
    """Recompute last-opportunity Q from goal conjunctions and response payoffs."""
    tree = episode.tree; root = tree.entries[episode.index]; result = []
    def payoff(node):
        c = node.state.snapshot_commitments()
        done = [all(c[a.player_id][a.action_id] for a in g.required_actions) for g in tree.rules.spec.goals]
        return np.array([[sum(v*d for v, d in zip(row, done)) for row in w] for w in tree.worlds], float)
    for child in root.children:
        entry = tree.entries[child]
        if entry.actor is None:
            result.append(payoff(entry.node)); continue
        if entry.node.pending is None or any(tree.entries[c].actor is not None for c in entry.children):
            return None
        av = np.array([payoff(tree.entries[c].node) for c in entry.children])
        own = av[:, :, entry.actor]; social = av.sum(axis=2)-own
        best = own >= own.max(axis=0)-1e-9
        best &= social >= np.where(best, social, -np.inf).max(axis=0)-1e-9
        policy = best/best.sum(axis=0)
        if any(not np.allclose(policy[:, ids], policy[:, ids[:1]], atol=1e-9, rtol=0)
               for ids in tree.information_groups[child]): return None
        result.append(np.einsum('aw,awp->wp', policy, av))
    return np.array(result)


def audit(tasks, samples, sample_tasks):
    from training.b_sft.social_named_probe import request
    indexed = {t['id']: t for t in sample_tasks}
    frozen = read('new/local_data/social_runs/bp_soc_download/846561.952bhmc2/bundle/requests.jsonl')
    for row in frozen:
        t = indexed[row['task_id']]; fresh = request(t, 'action_tools', t['name_variant'])
        for key in ('tools',): assert fresh[key] == row['request'][key]
        for i in (0, -1): assert fresh['messages'][i] == row['request']['messages'][i]
        visible = json.dumps(row['request'])
        assert not any(s in visible for s in ('type_catalogues', 'policy_sha256', 'action_values',
                                              'proposer_action', 'This is a small teaching game.'))
    unique = list({t['native_task_id']: t for t in tasks}.values())
    cache = {}; rows = []
    for task in unique:
        inp = task['input']; gold = task['teacher']; raw, own = reconstruct(inp)
        key = json.dumps([raw, inp['imposed_setup']], sort_keys=True)
        if key not in cache:
            e = PrivateEpisode(raw, inp['imposed_setup'])
            cache[key] = (e, audit_native(e.tree), independent_backward(e.tree))
        root, native, independent = cache[key]; e = copy(root)
        for event in inp['voluntary_history']: e.observe(event)
        node = e.tree.entries[e.index].node
        assert node.state.public_state() == inp['current_state']
        assert (None if node.pending is None else node.pending.to_dict()) == inp['pending_offer']
        facts = [(r['player'], r['goal'], VALUES[r['preference']]) for r in inp['private_results']]
        r = dict(source=task['source'], task=task['task'], skill=task['skill'], stage=task['stage'],
                 worlds=len(e.tree.worlds), tree_nodes=len(e.tree.entries), native=native,
                 independent_backward=independent, regenerated_label=True)
        if task['task'] == 'B':
            q = inp['queries'][0]
            actual = e.belief(q['player'], q['goal'], observer=inp['observer'], own=own, private_results=facts)
            assert {k: actual[k] for k in gold['gold']} == gold['gold'], task['source']
            np.testing.assert_allclose([actual['preference_weights'][v] for v in VALUES],
                                       [gold['preference_weights'][v] for v in VALUES], atol=1e-9, rtol=0)
            r['gold'] = gold['gold']
            r['direct_answer'] = any(p == q['player'] and g == q['goal'] for p, g, v in facts)
            if 'previous_belief' in inp:
                old = copy(root)
                if inp.get('new_history'):
                    for event in inp['voluntary_history'][:-len(inp['new_history'])]: old.observe(event)
                    slots = observed_slots(old.tree.entries[old.index].node, inp['observer'])
                    previous = old.belief(q['player'], q['goal'], observer=inp['observer'], own=own,
                                         private_results=[f for f in facts if f[:2] in slots])
                else:
                    # Assisted pre-answer exercise: public state is unchanged by
                    # private delivery. Do not condition on the newly received value.
                    for event in inp['voluntary_history']: old.observe(event)
                    weights = old.weights * np.array([w[inp['observer']] == own for w in old.tree.worlds])
                    weights /= weights.sum()
                    marginal = {k: sum(p for p, w in zip(weights, old.tree.worlds) if w[q['player']][q['goal']] == v)
                                for k, v in VALUES.items()}
                    possible = [k for k, p in marginal.items() if p > 0]
                    leaders = [k for k in possible if marginal[k] >= max(marginal.values())-1e-9]
                    previous = dict(possible_preferences=possible, favored=leaders[0] if len(leaders) == 1 else 'undetermined')
                assert {k: previous[k] for k in inp['previous_belief']} == inp['previous_belief'], task['source']
                r['previous_belief_checked'] = True
        else:
            choices = e.choices(own, facts)
            assert choices['actions'] == inp['legal_actions']
            manual = independent_final_actions(e)
            r['independent_final_response_values'] = manual is not None
            if manual is not None:
                np.testing.assert_allclose(manual, [e.tree.values[c] for c in e.tree.entries[e.index].children], atol=1e-9, rtol=0)
            if 'qualitative_certificate' in gold:
                entry = e.tree.entries[e.index]
                payoffs = np.array([e.tree.values[c] for c in entry.children])
                np.testing.assert_allclose(payoffs, gold['per_world_payoffs'], atol=1e-9, rtol=0)
                cert = robust_actions(payoffs, inp['player'], e.tree.worlds, gold['claims'],
                                      own_tolerance=.1, social_tolerance=.1, envelopes=gold['audit_envelopes'])
                accepted = cert['acceptable']; r['qualitative_status'] = cert['status']
            else:
                np.testing.assert_allclose(choices['values'], gold['action_values'], atol=1e-9, rtol=0)
                accepted = acceptable(choices['values'], inp['player'])
            assert [choices['actions'][i] for i in accepted] == gold['acceptable_actions'], task['source']
            r['accepted_kinds'] = sorted({a.get('action', a.get('response')) for a in gold['acceptable_actions']})
        rows.append(r)
        print(json.dumps(dict(source=r['source'], independent=independent)), flush=True)
    by_id = {t['id']: t for t in sample_tasks}; grouped = defaultdict(list)
    for s in samples: grouped[s['task_id']].append(s)
    groups = []
    for tid, ss in grouped.items():
        assert len(ss) == 2
        rewards = [s['score']['reward'] for s in ss]; success = sum(s['score']['correct'] for s in ss)
        tag = 'all_correct' if success == 2 else 'mixed_success' if success else 'no_success'
        groups.append(dict(task_id=tid, source=by_id[tid]['source'], task=by_id[tid]['task'],
            rewards=rewards, status=tag, wrong_gets_positive_advantage=success == 0 and len(set(rewards)) > 1))
    b = [r for r in rows if r['task'] == 'B']; p = [r for r in rows if r['task'] == 'P']
    summary = dict(unique_tasks=len(rows), native_roots=len(cache),
        frozen_task_prompts_and_tools_checked=len(frozen),
        kinds=dict(Counter(r['task'] for r in rows)),
        independent_backward_tasks=sum(r['independent_backward'] for r in rows),
        independent_final_response_tasks=sum(r.get('independent_final_response_values', False) for r in rows),
        b_set_sizes=dict(Counter(len(r['gold']['possible_preferences']) for r in b)),
        b_skills=dict(Counter(r['skill'] for r in b)),
        b_direct_answers=sum(r['direct_answer'] for r in b),
        b_previous_beliefs_checked=sum(r.get('previous_belief_checked', False) for r in b),
        b_fullset_undetermined_shortcut=sum(len(r['gold']['possible_preferences']) == 3 and r['gold']['favored'] == 'undetermined' for r in b),
        p_accepted_kind_profiles=dict(Counter(','.join(r['accepted_kinds']) or 'ambiguous' for r in p)),
        group_statuses=dict(Counter(g['status'] for g in groups)),
        false_positive_advantage_groups=sum(g['wrong_gets_positive_advantage'] for g in groups),
        stages=dict(Counter(r['stage'] for r in rows)),
        scope='Selected-policy re-solve from visible facts; independent induction only where information-compatible. Qualitative checks are conditional on documented language envelopes.')
    return dict(summary=summary, tasks=rows, groups=groups)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--out', required=True); args = parser.parse_args()
    result = audit(read('new/local_data/social_runs/bp_readable_prompt_review_v2/tasks.jsonl'),
        read('new/local_data/social_runs/bp_soc_download/846561.952bhmc2/local_scoring/scored_samples.jsonl'),
        read('new/local_data/social_runs/bp_soc_probe_r1/tasks.jsonl'))
    path = Path(args.out); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result['summary'], ensure_ascii=False, indent=2))
