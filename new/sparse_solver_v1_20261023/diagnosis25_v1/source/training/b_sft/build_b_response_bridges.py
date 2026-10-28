"""Minimal behavioral B lessons, with independent terminal-response certificates.

Uses the existing native game, selected teacher, readable prompt and binary
reward. Nothing here changes outcome self-play or the frozen B/P baseline.
The response has only two alternatives; every goal payoff is checked directly.
"""
import argparse
from collections import Counter
from copy import copy, deepcopy
from fractions import Fraction
import hashlib
from itertools import product
import json
from pathlib import Path

import numpy as np

from training.b_sft.bp_semantics import semantic_id
from training.b_sft.build_bp_pilot import make_task, topology
from training.b_sft.debug.audit_readable_pretraining import reconstruct, independent_backward
from training.b_sft.prepare_no_catalogue_probe import expand_support
from training.b_sft.social_bp_training import native_completion, reward
from training.b_sft.social_named_probe import request
from training.b_sft.social_private_teacher import PrivateEpisode, audit_native

VERSION = 'b-response-bridges-v1'
LABELS = ('want', 'neutral', 'avoid')


def fixture(shape, mode):
    """One hidden goal, plus an explicitly wanted background goal.

    With a neutral observer, the public generation constraint makes the prior
    want/avoid. This is a derived prior, never a hand-restricted type catalogue.
    """
    if shape in ('disjoint', 'joint_constraint'):
        counts, refs = [2, 2], [[(0, 0), (1, 0)], [(0, 1), (1, 1)]]
    elif shape in ('shared_partner_commitment', 'joint_constraint_shared'):
        counts, refs = [2, 1], [[(0, 0), (1, 0)], [(0, 1), (1, 0)]]
    elif shape == 'coupled_payoffs':
        counts, refs = [1, 1], [[(0, 0), (1, 0)]] * 2
    elif shape in ('response_likelihood', 'response_likelihood_shared', 'joint_payoffs', 'joint_payoffs_shared'):
        counts = [2, 1 if shape.endswith('_shared') else 2]
        refs = [[(0, 0), (1, 0)], [(0, 0), (1, 0)], [(0, 1), (1, counts[1]-1)]]
    else:
        raise ValueError(shape)
    own = [dict(binary=0, altruistic=1, conflict=-1).get(mode, -1), 1]
    partner = [[v, 1] for v in (1, 0, -1)]
    if shape.startswith('response_likelihood'):
        own, partner = [1, -1, 1], [[v, 0, 1] for v in (1, 0, -1)]
    elif shape.startswith('joint_constraint'):
        own, partner = [1, -1], [list(row) for row in product((1, 0, -1), repeat=2)]
    elif shape.startswith('joint_payoffs'):
        own = [1, 1, 1]
        partner = [[a, b, 1] for a, b in product((1, 0, -1), repeat=2)]
    raw = dict(id=f'{VERSION}:{shape}:{mode}', ego=0, own_preferences=own, history=[],
        type_catalogues={'0': [own], '1': partner}, game=dict(n_players=2,
            n_actions_per_player=counts, max_changes=1, menu_enabled=False,
            round_robin=[1, 0], goals=[dict(goal_id=g, binary=True,
                required_actions=[dict(player_id=p, action_id=a) for p, a in rs])
                for g, rs in enumerate(refs)]))
    return expand_support(raw)[:2]


def offer(raw, goal):
    vectors = [[0]*n for n in raw['game']['n_actions_per_player']]
    for ref in raw['game']['goals'][goal]['required_actions']:
        vectors[ref['player_id']][ref['action_id']] = 1
    return dict(action='OFFER', partner_id=1,
                proposer_action=vectors[0], partner_action=vectors[1])


def response_certificate(root, response):
    """Exact payoff/likelihood calculation without solver values or policy.

    Applicable only to this final response with hidden slots owned by the
    responder. Other-player payoffs are public, so this calculation does
    not grant the responder knowledge they lack.
    """
    entry = root.tree.entries[root.index]
    assert entry.actor == 1 and entry.node.pending is not None
    assert all(root.tree.entries[c].actor is None for c in entry.children)
    assert all(w[0] == root.tree.worlds[0][0] for w in root.tree.worlds)
    assert np.allclose(root.weights, np.ones(len(root.weights))/len(root.weights))
    state = entry.node.state.public_state()
    before = state['commitments']
    pending = entry.node.pending.to_dict()
    accepted = deepcopy(before)
    accepted[0] = pending['proposer_action']
    accepted[1] = pending['partner_action']
    goals = root.raw['game']['goals']
    def completed(commitments):
        return [all(commitments[r['player_id']][r['action_id']]
                    for r in g['required_actions']) for g in goals]
    done = {'ACCEPT': completed(accepted), 'REJECT': completed(before)}
    rows, posterior = [], {v: Fraction(0) for v in LABELS}
    policies = {name: [] for name in done}
    for world in root.tree.worlds:
        payoffs = {name: [sum(p*d for p, d in zip(prefs, achieved)) for prefs in world]
                   for name, achieved in done.items()}
        ranks = {name: (u[1], u[0]) for name, u in payoffs.items()}
        best = max(ranks.values())
        probs = {name: Fraction(int(rank == best), sum(r == best for r in ranks.values()))
                 for name, rank in ranks.items()}
        for name in policies:
            policies[name].append(float(probs[name]))
        value = {1: 'want', 0: 'neutral', -1: 'avoid'}[world[1][0]]
        posterior[value] += probs[response] / len(root.tree.worlds)
        rows.append(dict(preference=value, responder_preferences=list(world[1]), payoffs=payoffs,
                         response_likelihood={k: str(v) for k, v in probs.items()}))
    for i, action in enumerate(entry.actions):
        np.testing.assert_allclose(policies[action.to_dict()['response']],
                                   root.tree.policy[root.index][i], atol=1e-9, rtol=0)
    mass = sum(posterior.values())
    if not mass:
        return None
    posterior = {k: v/mass for k, v in posterior.items()}
    possible = [k for k, v in posterior.items() if v]
    leaders = [k for k in possible if posterior[k] == max(posterior.values())]
    return dict(gold=dict(possible_preferences=possible,
                favored=leaders[0] if len(leaders) == 1 else 'undetermined'),
        completed_goals=done, world_checks=rows,
        posterior={k: str(v) for k, v in posterior.items()},
        scope='Exact final-response check; responder knows every fact used in their payoff comparison.')


def build_tasks():
    tasks = []
    configs = [(shape, mode) for shape in ('disjoint', 'shared_partner_commitment')
               for mode in ('binary', 'altruistic', 'conflict')]
    configs += [('coupled_payoffs', 'net_payoff'), ('response_likelihood', 'favored'),
                ('response_likelihood_shared', 'favored'),
                ('joint_constraint', 'favored_disappears'), ('joint_constraint_shared', 'favored_disappears'),
                ('joint_payoffs', 'favored_appears'), ('joint_payoffs_shared', 'favored_appears')]
    for shape, mode in configs:
        raw, public = fixture(shape, mode)
        goals = ([1] if shape.startswith('joint_constraint') else [0] if shape == 'coupled_payoffs'
                 or shape.startswith('joint_payoffs') else [0, len(raw['game']['goals'])-1])
        for offered_goal in goals:
            setup = [dict(action='PASS'), offer(raw, offered_goal)]
            root = PrivateEpisode(raw, setup)
            prior = root.belief(1, 0, observer=0, own=raw['own_preferences'])
            prior = {k: prior[k] for k in ('possible_preferences', 'favored')}
            for response in ('ACCEPT', 'REJECT'):
                cert = response_certificate(root, response)
                if cert is None:
                    continue  # A zero-likelihood action cannot become behavioral evidence.
                e = copy(root); event = dict(response=response); e.observe(event)
                for previous in (None, prior):
                    level = (0 if mode == 'binary' else 4 if mode.startswith('favored_')
                             else 3 if mode == 'favored' else 2 if mode == 'net_payoff' else 1)
                    t = make_task(e, public, setup, [event], 'B', min(2, level//2),
                        topology(raw), previous=previous, source=raw['id'])
                    assert t['teacher']['gold'] == cert['gold']
                    t.update(b_lesson_level=level, b_lesson=mode,
                        evidence_relation='joint_constraint' if shape.startswith('joint_constraint')
                            else 'unrelated' if offered_goal else 'target',
                        short_teaching=True, direct_answer=False, bridge_version=VERSION)
                    # Pair by physical game/offer and supplied-prior presence,
                    # allowing response or known observer preference to differ.
                    t['contrast_group'] = hashlib.sha256(json.dumps(
                        [shape, offered_goal, previous is not None]).encode()).hexdigest()[:20]
                    t['teacher']['response_certificate'] = cert
                    t['semantic_id'] = semantic_id(t)
                    tasks.append(t)
    assert len({t['semantic_id'] for t in tasks}) == len(tasks)
    return tasks


def verify_task(t):
    """Reconstruct from visible facts; reject even a self-consistent wrong label."""
    inp = t['input']; raw, own = reconstruct(inp)
    root = PrivateEpisode(raw, inp['imposed_setup'])
    assert independent_backward(root.tree)
    native = audit_native(root.tree)
    assert native['all_values_match']
    assert root.tree.certificate['policy_sha256'] == t['teacher']['policy_sha256']
    assert len(inp['voluntary_history']) == 1
    cert = response_certificate(root, inp['voluntary_history'][0]['response'])
    assert cert == t['teacher']['response_certificate']
    if 'previous_belief' in inp:
        old = root.belief(1, 0, observer=0, own=own)
        assert {k: old[k] for k in inp['previous_belief']} == inp['previous_belief']
    root.observe(inp['voluntary_history'][0])
    belief = root.belief(1, 0, observer=0, own=own)
    assert {k: belief[k] for k in cert['gold']} == t['teacher']['gold'] == cert['gold']
    for value in LABELS:
        assert abs(belief['preference_weights'][value] - float(Fraction(cert['posterior'][value]))) < 1e-9
        assert abs(t['teacher']['preference_weights'][value] - belief['preference_weights'][value]) < 1e-9
    assert root.tree.entries[root.index].node.state.public_state() == inp['current_state']
    req = request(t, 'action_tools', t['name_variant'])
    assert {x['function']['name'] for x in req['tools']} == {'SUBMIT_BELIEFS'}
    assert req['max_tokens'] == 1024
    visible = json.dumps(req)
    for key in ('response_certificate', 'preference_weights', 'type_catalogues', 'policy_sha256'):
        assert key not in visible
    assert reward(t, native_completion(t))['reward'] == 1
    return dict(id=t['id'], native=native, independent_response=True,
                previous_checked='previous_belief' in inp)


def write_pack(out, baseline):
    out = Path(out); out.mkdir(parents=True, exist_ok=False)
    baseline = Path(baseline)
    old = [json.loads(s) for s in baseline.read_text().splitlines()]
    families = {t['family']: t['split'] for t in old}
    tasks = build_tasks()
    for t in tasks:
        # Never move an existing held-out family into teaching. New mechanisms
        # are development data; the existing test set is not probed here.
        t['split'] = families.get(t['family'], 'train')
    checks = [verify_task(t) for t in tasks]
    (out/'tasks.jsonl').write_text(''.join(json.dumps(t)+'\n' for t in tasks))
    groups = {}
    for t in tasks:
        groups.setdefault(t['contrast_group'], []).append(t)
    pairs = [dict(group=k, members=[t['id'] for t in ts],
                  distinct_answers=len({t['answer_signature'] for t in ts}))
             for k, ts in groups.items()]
    summary = dict(version=VERSION, tasks=len(tasks), direct_reading=0,
        skills=dict(Counter(t['skill'] for t in tasks)),
        levels=dict(Counter(t['b_lesson_level'] for t in tasks)),
        set_sizes=dict(Counter(len(t['teacher']['gold']['possible_preferences']) for t in tasks)),
        splits=dict(Counter(t['split'] for t in tasks)),
        families=len({t['family'] for t in tasks}),
        nonredundant_favored=sum(len(t['teacher']['gold']['possible_preferences']) > 1
            and t['teacher']['gold']['favored'] != 'undetermined' for t in tasks),
        favored_only_updates=sum(t['input'].get('previous_belief', {}).get('possible_preferences')
            == t['teacher']['gold']['possible_preferences'] and t['skill'] == 'update' for t in tasks),
        baseline_tasks_sha256=hashlib.sha256(baseline.read_bytes()).hexdigest(),
        tasks_sha256=hashlib.sha256((out/'tasks.jsonl').read_bytes()).hexdigest(),
        learner_tested=False, scope='B replacement candidates, not a newly validated full training curriculum.')
    (out/'audit.json').write_text(json.dumps(dict(summary=summary, checks=checks, contrasts=pairs), indent=2)+'\n')
    requests = []
    for t in tasks:
        if t['split'] == 'test':
            continue
        req = request(t, 'action_tools', t['name_variant'])
        req.update(temperature=.8, top_p=1., top_k=-1, repetition_penalty=1.)
        requests.append(dict(task_id=t['id'], task='B', split=t['split'], pool=t['pool'],
                             stage=t['stage'], output_arm='action_tools', request=req))
    (out/'requests.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in requests))
    (out/'probe_manifest.json').write_text(json.dumps(dict(version=VERSION,
        tasks_sha256=summary['tasks_sha256'],
        requests_sha256=hashlib.sha256((out/'requests.jsonl').read_bytes()).hexdigest(),
        conditions=len(requests), group_size=8, formal_requests=len(requests)*8,
        test_requests=0, response_budget=1024, output_arm='action_tools'), indent=2)+'\n')
    examples = []
    for level in sorted({t['b_lesson_level'] for t in tasks}):
        t = next(t for t in tasks if t['split'] != 'test' and t['b_lesson_level'] == level
                 and t['evidence_relation'] != 'unrelated' and t['skill'] == 'update')
        examples.append(f'## Lesson level {level}: {t["id"]}\n\n'+request(t, 'action_tools', t['name_variant'])['messages'][1]['content']+
                        '\n\n### Local teacher check (never sent to learner)\n\n```json\n'+json.dumps(t['teacher']['response_certificate'], indent=2)+'\n```')
    (out/'review.md').write_text('# B response bridges: visible prompts and separate checks\n\n'+'\n\n'.join(examples)+'\n')
    return summary


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--out', required=True)
    p.add_argument('--baseline', default='examples/social_bp/data/tasks.jsonl')
    a = p.parse_args()
    print(json.dumps(write_pack(a.out, a.baseline), indent=2))
