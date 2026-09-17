"""Read-only BP interface audit; no model calls, training, or label changes.

Run from repository root: python new/bp_interface_audit_20260917/audit.py
This is a finite counterexample audit, NOT exhaustive belief-cell certification.
"""
from collections import Counter, defaultdict
from fractions import Fraction
from itertools import combinations
from pathlib import Path
import hashlib
import json
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from training.b_sft.preference_contract import belief, world_weights
from training.b_sft.social_bp_curriculum import acceptable
from training.b_sft.social_p_qualitative import robust_actions
from training.b_sft.social_named_probe import Names
from training.b_sft.debug.audit_readable_pretraining import reconstruct

OUT = Path(__file__).resolve().parent
VALUES = {'want': 1, 'neutral': 0, 'avoid': -1}
CONTEXT = ('game', 'player', 'observer', 'own_preferences', 'public_preferences',
           'private_results', 'current_state', 'pending_offer', 'imposed_setup',
           'voluntary_history', 'background_prior', 'partner_policy', 'knowledge_rule')


def stable(x):
    return json.dumps(x, sort_keys=True, separators=(',', ':'))


def context(t):
    return stable({k: t['input'].get(k) for k in CONTEXT})


def semantic_context(t):
    """Ignore prose, seed, display IDs, and redundant serialized state fields."""
    i = t['input']; g = i['game']; s = i['current_state']
    game = {k: g.get(k) for k in ('n_players', 'n_actions_per_player', 'goals',
                                'round_robin', 'max_changes', 'forbidden_actions')}
    state = {k: s.get(k) for k in ('commitments', 'turn_index',
                                  'investigation_remaining_by_player')}
    return stable([game, state, i['player'], i['own_preferences'],
        sorted(i['public_preferences'], key=stable), sorted(i['private_results'], key=stable),
        i['pending_offer'], i['imposed_setup'], i['voluntary_history'], i['background_prior']])


def completion(game, commitments):
    result = []
    for g in game['goals']:
        bits = [commitments[a['player_id']][a['action_id']] for a in g['required_actions']]
        result.append(float(all(bits)) if g['binary'] else sum(bits) / len(bits))
    return np.array(result)


def independent_final_payoffs(t):
    """Terminal utility + responder tie rule; never read teacher policy/Q values.

    Perfect-world response choices are used ONLY if invariant within each
    responder information set. Otherwise decline the independent certificate.
    """
    i = t['input']; worlds = np.array(t['teacher']['worlds'])
    state = i['current_state']; game = i['game']
    assert len(game['round_robin']) - state['turn_index'] == 1
    base = state['commitments']
    reject = np.einsum('wpg,g->wp', worlds, completion(game, base))
    payoffs = []
    for a in i['legal_actions']:
        c = [row[:] for row in base]
        if 'response' in a:
            if a['response'] == 'REJECT':
                payoffs.append(reject); continue
            offer = i['pending_offer']; proposer = state['current_proposer']
        elif a['action'] in ('PASS', 'INVESTIGATE'):
            payoffs.append(reject); continue
        else:
            offer = a; proposer = i['player']
        responder = offer['partner_id']
        c[proposer] = offer['proposer_action']; c[responder] = offer['partner_action']
        accept = np.einsum('wpg,g->wp', worlds, completion(game, c))
        if 'response' in a:
            payoffs.append(accept); continue
        delta = accept - reject
        own = delta[:, responder]; social = delta.sum(axis=1) - own
        probability = np.where(own > 1e-9, 1., np.where(own < -1e-9, 0.,
            np.where(social > 1e-9, 1., np.where(social < -1e-9, 0., .5))))
        slots = [(e['player'], e['goal']) for e in state['transcript']
                 if e['action'] == 'INVESTIGATE' and e['proposer_id'] == responder]
        groups = defaultdict(list)
        for w, p in zip(worlds, probability):
            groups[(tuple(w[responder]), tuple(w[x, g] for x, g in slots))].append(p)
        if any(max(ps) != min(ps) for ps in groups.values()):
            return None
        payoffs.append(probability[:, None] * accept + (1 - probability[:, None]) * reject)
    return np.array(payoffs)


def conditional_prior(t):
    i = t['input']; worlds = t['teacher']['worlds']
    known = i['supplied_belief']['known_preferences']
    assert not i['voluntary_history'], 'Behavior requires policy replay'
    p = world_weights(worlds, i['background_prior'])
    p *= [all(w[f['player']][f['goal']] == VALUES[f['preference']] for f in known)
          for w in worlds]
    assert p.sum() > 0
    return p / p.sum()


def distribution(t):
    i = t['input']; worlds = t['teacher']['worlds']; b = i['supplied_belief']
    if 'joint_distribution' not in b:
        return conditional_prior(t)
    p = np.zeros(len(worlds))
    for row in b['joint_distribution']:
        facts = b['known_preferences'] + row['preferences']
        ids = [j for j, w in enumerate(worlds)
               if all(w[f['player']][f['goal']] == VALUES[f['preference']] for f in facts)]
        assert len(ids) == 1
        p[ids[0]] += float(Fraction(row['probability']))
    np.testing.assert_allclose(p.sum(), 1., atol=1e-12)
    return p


def marginal_labels(t, p):
    worlds = t['teacher']['worlds']; rows = []
    for slot in t['input']['supplied_belief']['unresolved_preferences']:
        player, goal = slot['player'], slot['goal']
        mass = {name: float(sum(v for v, w in zip(p, worlds) if w[player][goal] == value))
                for name, value in VALUES.items()}
        rows.append(dict(player=player, goal=goal, probabilities=mass, **belief(mass)))
    return rows


def label_key(rows):
    return stable([{k: v for k, v in r.items() if k != 'probabilities'} for r in rows])


def named_actions(t, actions):
    i = t['input']; names = Names(i, t.get('name_variant', 0))
    return [names.action(a, i['player'], i['current_state']['commitments']) for a in actions]


def accepted(t, p):
    values = np.einsum('awp,w->ap', np.array(t['teacher']['per_world_payoffs']), p)
    ids = acceptable(values, t['input']['player'], actions=t['input']['legal_actions'])
    return ids, values


def main():
    sources = [ROOT / f'examples/social_mixed/data_distribution_v1/bp_{s}.jsonl'
               for s in ('train', 'validation')]
    rows = [json.loads(line) for path in sources for line in path.read_text().splitlines()]
    report = dict(scope='Finite existing-task pairs; no exhaustive posterior search or model evaluation',
                  sources={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
                  counts=dict(Counter(t['kernel'] for t in rows)))
    bs = defaultdict(list)
    for t in rows:
        if t['task'] == 'B': bs[context(t)].append(t['id'])
    report['exact_context_bp_matches'] = [dict(p=t['id'], b=bs[context(t)]) for t in rows
                                         if t['task'] == 'P' and context(t) in bs]
    report['exact_context_fields'] = CONTEXT
    semantic_b = defaultdict(list)
    for t in rows:
        if t['task'] == 'B': semantic_b[semantic_context(t)].append(t['id'])
    report['semantic_context_bp_matches'] = [dict(p=t['id'], b=semantic_b[semantic_context(t)])
        for t in rows if t['task'] == 'P' and semantic_context(t) in semantic_b]
    p2 = [t for t in rows if t['kernel'] == 'P2']; entries = {}; groups = defaultdict(list)
    independent_count = 0
    for t in p2:
        # Reconstruct possible worlds from game constraints and visible facts,
        # independently of the stored teacher world list.
        from itertools import product
        raw, own = reconstruct(t['input'])
        rebuilt = set(product(*(map(tuple, raw['type_catalogues'][str(p)])
                                for p in range(t['input']['game']['n_players']))))
        assert rebuilt == {tuple(map(tuple, w)) for w in t['teacher']['worlds']}
        p = distribution(t); ids, values = accepted(t, p)
        assert [t['input']['legal_actions'][j] for j in ids] == t['teacher']['acceptable_actions']
        np.testing.assert_allclose(values, t['teacher']['action_values'], atol=1e-9)
        manual = independent_final_payoffs(t)
        if manual is not None:
            np.testing.assert_allclose(manual, t['teacher']['per_world_payoffs'], atol=1e-9)
            independent_count += 1
        natural = conditional_prior(t)
        inp = t['input']
        observed = inp['public_preferences'] + inp['private_results'] + [
            dict(player=inp['player'], goal=g, preference=inp['own_preferences'][f'goal_{g}'])
            for g in range(len(inp['game']['goals']))]
        known_grounded = all(f in observed for f in inp['supplied_belief']['known_preferences'])
        entries[t['id']] = dict(id=t['id'], split=t['split'], origin_id=t['origin_id'],
            case=t.get('p123_case'), mode=t['completion_mode'], profile=t['background_profile'],
            labels=marginal_labels(t, p), distribution=p.tolist(),
            acceptable_indices=ids, own_action_values=values[:, t['input']['player']].tolist(),
            named_acceptable=named_actions(t, t['teacher']['acceptable_actions']),
            independent_payoffs=manual is not None,
            supplied_equals_conditional_prior=bool(np.allclose(p, natural, atol=1e-10, rtol=0)),
            known_facts_all_observed=known_grounded,
            conditional_prior=natural.tolist(),
            # Zero voluntary actions means these priors need no teacher likelihood update.
            voluntary_events=len(t['input']['voluntary_history']),
            worlds=t['teacher']['worlds'])
        # Keep known facts, unresolved slots and legal actions fixed too.
        b = t['input']['supplied_belief']
        groups[stable([context(t), b['known_preferences'], b['unresolved_preferences'],
                       t['input']['legal_actions']])].append(t)
    pairs = []; same_label_pairs = 0
    for group in groups.values():
        for a, b in combinations(group, 2):
            aa, bb = entries[a['id']], entries[b['id']]
            if label_key(aa['labels']) != label_key(bb['labels']): continue
            same_label_pairs += 1
            assert a['teacher']['worlds'] == b['teacher']['worlds']
            np.testing.assert_allclose(a['teacher']['per_world_payoffs'], b['teacher']['per_world_payoffs'], atol=1e-9)
            if set(aa['acceptable_indices']) & set(bb['acceptable_indices']): continue
            equal_marginals = all(np.allclose(list(x['probabilities'].values()), list(y['probabilities'].values()),
                                             atol=1e-12, rtol=0) for x, y in zip(aa['labels'], bb['labels']))
            pairs.append(dict(a=a['id'], b=b['id'], same_exact_marginals=equal_marginals,
                mode=a['completion_mode'], profile=a['background_profile'],
                a_actions_under_b_min_regret=float(max(bb['own_action_values']) - max(bb['own_action_values'][j] for j in aa['acceptable_indices'])),
                b_actions_under_a_min_regret=float(max(aa['own_action_values']) - max(aa['own_action_values'][j] for j in bb['acceptable_indices']))))
    report['p2'] = dict(total=len(p2), independently_verified_payoffs=independent_count,
        explicit_joint=sum('joint_distribution' in t['input']['supplied_belief'] for t in p2),
        controlled_same_label_pairs=same_label_pairs, disjoint_pairs=pairs,
        tasks_in_disjoint_pairs=len({p[k] for p in pairs for k in ('a', 'b')}),
        note='Pairs/background repeats are not independent structures; all P2 are final-opportunity tasks.')
    # Recheck P3's own supplied interval contract, separate from B compression.
    p3 = [t for t in rows if t['kernel'] == 'P3']
    for t in p3:
        g = t['teacher']; i = t['input']
        cert = robust_actions(g['per_world_payoffs'], i['player'], g['worlds'], g['claims'],
                              own_tolerance=.1, social_tolerance=.1, envelopes=g['audit_envelopes'],
                              offer_response=i['pending_offer'] is not None)
        assert [i['legal_actions'][j] for j in cert['acceptable']] == g['acceptable_actions']
    report['p3'] = dict(interval_certificates_recomputed=len(p3), all_match=True,
        note='Uses existing LP implementation; does not certify B labels sufficient for P3.')
    # Does an immediate decision at a B endpoint actually need partner belief?
    b2 = Counter()
    for t in rows:
        if t['kernel'] != 'B2': continue
        i = t['input']; state = i['current_state']; off = i['pending_offer']
        assert off['partner_id'] == i['player']
        assert len(i['game']['round_robin']) - state['turn_index'] == 1
        before = state['commitments']; after = [v[:] for v in before]
        after[state['current_proposer']] = off['proposer_action']; after[off['partner_id']] = off['partner_action']
        delta = completion(i['game'], after) - completion(i['game'], before)
        own = sum(delta[g] * VALUES[i['own_preferences'][f'goal_{g}']] for g in range(len(delta)))
        if abs(own) > .1 + 1e-9: b2['own_strict_beyond_tolerance'] += 1
        elif np.max(abs(delta)) < 1e-9: b2['no_goal_completion_change'] += 1
        else: b2['own_tie_or_near_tie_needs_further_check'] += 1
    report['b_endpoint'] = dict(b2=dict(b2),
        b1_terminal=sum(t['kernel'] == 'B1' and t['input']['current_state']['turn_index'] == len(t['input']['game']['round_robin']) for t in rows),
        note='B2 strict own-utility responses do not require partner belief. This says nothing against B inference validity.')
    (OUT / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
    (OUT / 'p2_details.json').write_text(json.dumps(entries, indent=2) + '\n')
    print(json.dumps({**report, 'p2': {**report['p2'], 'disjoint_pairs': len(pairs)}}, indent=2))


if __name__ == '__main__':
    main()
