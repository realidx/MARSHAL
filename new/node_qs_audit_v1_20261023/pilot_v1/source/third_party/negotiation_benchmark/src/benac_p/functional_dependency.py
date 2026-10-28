"""Separate native B->P and P->B opportunities, selected without LLM answers.

No frozen-prior continuation search and no strict-update certificate is used.
The reference action still maximizes exact terminal utility over all legal actions.
"""
import math
from itertools import combinations

from benac_p.endgame import Node, SearchLimit
from benac_p.endgame_partner import InformationStateRequired, InconsistentPartnerHistory
from benac_p.schema import OfferProposal, MenuOffer

VERSION = 'functional-dependency-v1'
GROUPS = ('b_to_p', 'p_to_b')


def sensitivity(rows):
    """An action optimal under one supported type is costly under another.

    Shared optimal actions are allowed and remain correct. This certifies a
    consequential judgment error opportunity, not a mandatory action switch.
    """
    for first, second in combinations(rows, 2):
        for (left, lq), (right, rq) in ((first, second), (second, first)):
            li = [i for i, v in enumerate(lq) if max(lq)-v < 1e-9]
            for a in li:
                if max(rq)-rq[a] > 1e-9:
                    b = max(range(len(rq)), key=rq.__getitem__)
                    return dict(left_support=left, right_support=right,
                                action_indices=[a, b], left_q=lq, right_q=rq,
                                right_regret=max(rq)-rq[a],
                                tie_scope='Common optimal actions remain valid; no mandatory action switch or positive model repair is implied.')
    return None


def certify(f):
    # Cheap structural checks precede terminal-value computation.
    if len(f.support(f.root)) < 2 or len(f.search.actions(f.root)) < 2:
        return dict(version=VERSION, groups=[])
    q = f.search.q_values(f.root)
    typed = []
    for w in f.root.worlds:
        node = Node(f.root.state, (w,), f.root.pending)
        try:
            typed.append((f.support(node), [v for _, v in f.search.q_values(node)]))
        except InconsistentPartnerHistory:
            continue
    witness = sensitivity(typed)
    # Choose a deterministic first contrasting pair, not an MI-maximizing oracle.
    # Both arms must leave a next actual ego decision on every branch. Thus
    # evidence is measured before an opportunity to act, never only at game over.
    seen = []; pair = None
    for action, value in q:
        branches = f.window_step(f.root, action)
        if not branches or any(b.node.state.is_terminal for b in branches):
            continue
        entropy = sum(b.weight*math.log2(len(f.support(b.node))) for b in branches)
        channel = dict(action=action.to_dict(), value=value, posterior_entropy=entropy,
                       branches=[dict(weight=b.weight, support=f.support(b.node),
                                      history=f.history_text(b.node)) for b in branches])
        for previous in seen:
            if abs(previous['posterior_entropy']-entropy) > 1e-9:
                low, high = sorted((previous, channel), key=lambda c:-c['posterior_entropy'])
                pair = dict(low=low, high=high,
                            information_gap=low['posterior_entropy']-high['posterior_entropy'])
                break
        if pair is not None:
            break
        seen.append(channel)
    groups = ([GROUPS[0]] if witness else []) + ([GROUPS[1]] if pair else [])
    return dict(version=VERSION, groups=groups, belief_to_planning=witness,
                planning_to_belief=pair,
                scope='Separate functional opportunities; neither positive model repair nor information-mediated utility is guaranteed.')


def build(fixtures):
    from benac_p.endgame_diagnose import Suite, decode_action
    suite = Suite([])
    for f in fixtures:
        proof = certify(f)
        groups = f.raw.get('functional_groups', proof['groups'])
        if any(g not in proof['groups'] for g in groups):
            raise ValueError('Saved functional cohort no longer passes its certificate.')
        if not groups:
            continue
        suite.fixtures[f.id] = f
        suite.add_case(f, f.root, f.id+'/root')
        q = suite.cases[f.id+'/root']['q']; best = max(v for _, v in q)
        suite.add_arm(f, 'oracle', next(a for a, v in q if best-v < 1e-9))
        if 'p_to_b' in groups:
            pair = proof['planning_to_belief']
            for key, arm in [('low', 'low_information'), ('high', 'high_information')]:
                suite.add_arm(f, arm, decode_action(pair[key]['action']))
        suite.certificates[f.id] = dict(version=VERSION, bundle=f.bundle, split=f.split,
            condition='functional_dependency', groups=groups, functional=proof,
            primary_case=f.id+'/root', legal_history=True, independent_catalogues=True,
            full_native_actions=True, planning_history_included=True,
            remaining_proposal_turns=len(f.spec.round_robin)-f.root.state.turn_index,
            menu_actions=sum(isinstance(a, OfferProposal) and isinstance(a.offer, MenuOffer) for a, _ in q),
            partner_optimality=f.partner.specification())
    return suite


def readiness(suite, min_games):
    counts = {}; missing = []
    for split in ('discovery', 'confirmation'):
        for group in GROUPS:
            n = len({c['bundle'] for c in suite.certificates.values()
                     if c['split'] == split and group in c.get('groups', [])})
            counts[split+'/'+group] = n
            if n < min_games:
                missing.append(f'{split}/{group}: {n}/{min_games} independent games')
    return dict(passed=not missing, missing=missing, independent_games=counts,
                scope='Separate functional cohorts; a source game may contribute to both groups, not independent replications across groups.')


def mine(args, out):
    from types import SimpleNamespace
    from benac_p.endgame_diagnose import Fixture
    from benac_p.endgame_mine import candidates
    from benac_p.diagnose_suite import dump
    selected = []; certs = {}; attempts = []
    # Bounded query sampling and shorter positions; no strict certificate calls.
    for seed in range(args.seed, args.seed+args.candidate_seeds):
        for raw in candidates(seed, args.max_nodes, args.actions_per_player, args.n_goals,
                              args.rounds, args.unknown_goals, attempts.append,
                              args.max_remaining_turns, args.max_query_sets or 2):
            try:
                f = Fixture(raw, args.max_nodes)
                proof = certify(f)
                groups = [g for g in proof['groups'] if
                          len({c['bundle'] for c in certs.values() if c['split']==f.split and g in c['groups']}) < args.min_games_per_condition
                          and not any(c['bundle']==f.bundle and g in c['groups'] for c in certs.values())]
                attempts.append(dict(id=f.id, eligible=proof['groups'], selected=groups))
                if groups:
                    raw = dict(raw, functional_groups=groups)
                    selected.append(raw)
                    certs[f.id] = dict(bundle=f.bundle, split=f.split, groups=groups)
            except (SearchLimit, InformationStateRequired) as exc:
                attempts.append(dict(id=raw['id'], reason=str(exc)))
            if readiness(SimpleNamespace(certificates=certs), args.min_games_per_condition)['passed']:
                break
        ready = readiness(SimpleNamespace(certificates=certs), args.min_games_per_condition)
        dump(out/'readiness.json', ready)
        dump(out/'selection.json', dict(version=VERSION, fixtures=selected, attempts=attempts,
             next_seed=seed+1, complete=ready['passed'], max_query_sets=args.max_query_sets or 2))
        print(f'Functional selection seed {seed}: {ready["independent_games"]}', flush=True)
        if ready['passed']:
            break
    return dict(fixtures=selected, selection_version=VERSION)
