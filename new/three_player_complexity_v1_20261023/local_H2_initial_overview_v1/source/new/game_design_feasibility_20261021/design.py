"""Isolated parameterized native-game diagnostic; never a production overlay."""
from functools import lru_cache
from itertools import combinations, product

import numpy as np

from benac_p.endgame import Node
from benac_p.endgame import Endgame
from benac_p.schema import OfferProposal, GameSpec, Goal, ActionRef
from training.b_sft.preference_contract import profile
from training.b_sft.social_private_teacher import (
    PrivateInvestigationRules, PrivateQueryEvent, PrivateState, observed_slots,
)
from training.b_sft.social_terminal_teacher import Investigate

VERSION = 'parameterized-native-feasibility-v1'


class BudgetState(PrivateState):
    def __init__(self, spec, query_limit, offer_limit):
        super().__init__(spec)
        self.query_limit = query_limit
        self.offer_limit = offer_limit
        self.query_used = (0,) * spec.n_players
        self.offer_used = (0,) * spec.n_players

    def public_state(self):
        state = super().public_state()
        state.update(
            investigation_remaining_by_player=[self.query_limit-v for v in self.query_used],
            investigation_budget_scope='per player per game',
            offer_remaining_by_player=[self.offer_limit-v for v in self.offer_used],
            offer_used_by_player=list(self.offer_used),
        )
        return state


class BudgetRules(PrivateInvestigationRules):
    def __init__(self, raw, query_limit, offer_limit, query_targets='all'):
        for value in (query_limit, offer_limit):
            if type(value) is not int or value < 0:
                raise ValueError('Nonnegative integer budgets required')
        # The production catalogue admission rule requires every type to want
        # at least one goal and forbids any jointly all-neutral goal. Those are
        # dataset restrictions, not native transition/payoff requirements.
        # This isolated diagnostic explicitly removes those admission filters
        # to test the unconditioned independent prior. Never monkeypatch them.
        g = raw['game']; n = g['n_players']; ng = len(g['goals'])
        if g.get('menu_enabled',False):
            raise ValueError('MENU excluded')
        types = {int(p):tuple(tuple(row) for row in rows)
                 for p,rows in raw['type_catalogues'].items()}
        if set(types) != set(range(n)):
            raise ValueError('Exactly one catalogue per player required')
        for rows in types.values():
            if not rows or len(set(rows)) != len(rows) or any(
                    len(row)!=ng or any(v not in (-1,0,1) for v in row) for row in rows):
                raise ValueError('Invalid independent catalogue')
        spec = GameSpec(n,tuple(g['n_actions_per_player']),
            tuple(Goal(x['goal_id'],tuple(ActionRef(**a) for a in x['required_actions']),
                       x.get('binary',True)) for x in g['goals']),
            np.zeros((n,ng),dtype=np.int8),tuple(g['round_robin']),g['max_changes'],0,
            forbidden_actions=None,menu_enabled=False)
        def forbidden_kernel(_):
            raise AssertionError('Endgame partner kernel must not be used')
        self.base=Endgame(spec,raw['ego'],raw['own_preferences'],
            {p:rows for p,rows in types.items() if p!=raw['ego']},forbidden_kernel)
        self.worlds=tuple(product(*(types[p] for p in range(n))))
        self.catalogues=types
        self.spec=spec
        self.query_limit, self.offer_limit = query_limit, offer_limit
        if query_targets not in ('all','hidden-unobserved'):
            raise ValueError('Unknown query-target rule')
        self.query_targets=query_targets

    def initial(self):
        return Node(BudgetState(self.spec, self.query_limit, self.offer_limit), self.worlds)

    def public_game(self):
        game = super().public_game()
        game['variant'] = VERSION
        game['investigate']['budget'] = self.query_limit
        game['investigate']['targets'] = ('Any preference of another player, including known ones'
            if self.query_targets=='all' else
            'Only non-public preferences of another player not previously investigated by this player')
        game['offer_quota'] = dict(budget=self.offer_limit,
            scope='per player per game', charged='immediately on proposal',
            refunded=False, utility_penalty=0)
        return game

    def actions(self, node):
        ordinary = self.base.actions(node)
        actor = self.actor(node)
        if actor is None or node.pending is not None:
            return ordinary
        if node.state.offer_used[actor] >= self.offer_limit:
            ordinary = tuple(a for a in ordinary if not isinstance(a, OfferProposal))
        if node.state.query_used[actor] < self.query_limit:
            known=set(observed_slots(node,actor))
            ordinary += tuple(Investigate(p, g) for p in range(self.spec.n_players)
                if p != actor for g in range(len(self.spec.goals))
                if self.query_targets=='all' or ((p,g) not in known
                   and len({row[g] for row in self.catalogues[p]})>1))
        return ordinary

    def _apply(self, node, action):
        if action not in self.actions(node):
            raise ValueError('Illegal action under declared budgets')
        actor = self.actor(node)
        if not isinstance(action, Investigate):
            child = self.base._apply(node, action)
            if isinstance(action, OfferProposal):
                child.state.offer_used = tuple(v+int(p == actor)
                    for p, v in enumerate(node.state.offer_used))
            return child
        state = node.state.clone()
        state.transcript.append(PrivateQueryEvent(state.turn_index, actor,
            action.player, action.goal, state.snapshot_commitments()))
        state.query_used = tuple(v+int(p == actor) for p, v in enumerate(state.query_used))
        state.investigation_used = tuple(v >= self.query_limit for v in state.query_used)
        state.turn_index += 1
        return Node(state, node.worlds)


def generate(seed, *, players, actions, goals, rounds, hidden):
    """Uniform independent preferences; visibility chosen independently of values.

    No forced want, no rejection by payoffs/S/D, and no replacement of types.
    Every hidden cell has all three values. Public fixed facts may be neutral
    or avoid throughout: report such cases rather than invent positive labels.
    Goal requirements include 2+ players and may need multiple commitments
    from the same player. Binary/linear is independently sampled per goal.
    """
    if len(actions) != players or min(actions) < 1 or rounds < 1:
        raise ValueError('Invalid structure')
    rng = np.random.default_rng(seed)
    refs = [(p, a) for p, count in enumerate(actions) for a in range(count)]
    pool = [subset for size in range(2, min(3, len(refs))+1)
            for subset in combinations(refs, size)
            if len({p for p, _ in subset}) >= 2]
    if not 1 <= goals <= len(pool) or not 0 <= hidden <= players*goals:
        raise ValueError('Invalid number of goals or hidden preferences')
    chosen = rng.choice(len(pool), size=goals, replace=False)
    goal_rows = [dict(goal_id=i, binary=bool(rng.integers(2)),
        required_actions=[dict(player_id=p, action_id=a) for p,a in pool[int(index)]])
        for i,index in enumerate(chosen)]
    # The hidden mask does not inspect or condition on any preference value.
    cells = [(p,g) for p in range(players) for g in range(goals)]
    hidden_cells = {cells[int(i)] for i in rng.choice(len(cells), hidden, replace=False)}
    fixed = rng.choice([1,0,-1], size=(players,goals))
    types = {}
    for p in range(players):
        slots = [g for g in range(goals) if (p,g) in hidden_cells]
        rows = []
        for values in product([1,0,-1], repeat=len(slots)):
            row = fixed[p].tolist()
            for g,value in zip(slots, values):
                row[g] = value
            rows.append(row)
        types[str(p)] = rows
    order = list(map(int, rng.permutation(players)))
    return dict(game=dict(n_players=players, n_actions_per_player=list(actions),
        goals=goal_rows, round_robin=order*rounds, max_changes=1, menu_enabled=False),
        ego=0, own_preferences=types['0'][0], type_catalogues=types,
        background_prior=profile('balanced'), history=[])


def count_public_tree(rules):
    """Exact history multiplicities using cached physical-state subtree counts.

    This only counts the tree. It NEVER merges histories during solving or
    claims the merged states have the same information or strategic value.
    Independent of preferences, goal incidence and terminal utility.
    """
    spec = rules.spec
    n = spec.n_players
    if spec.max_changes != 1 or spec.forbidden_actions is not None:
        raise ValueError('Counting implementation requires max_changes=1 and no forbidden actions')
    allmasks = [(1 << count)-1 for count in spec.n_actions_per_player]
    hidden_per_player=[sum(len({row[g] for row in rules.catalogues[p]})>1
        for g in range(len(spec.goals))) for p in range(n)]

    @lru_cache(None)
    def count(turn, masks, queries, offers):
        if turn == len(spec.round_robin):
            return (1, 1, 0)
        actor = spec.round_robin[turn]
        nodes, leaves, responses = count(turn+1, masks, queries, offers) # PASS
        nodes += 1 # current proposal node
        if queries[actor] < rules.query_limit:
            q = list(queries); q[actor] += 1
            child = count(turn+1, masks, tuple(q), offers)
            multiplicity = ((n-1)*len(spec.goals) if rules.query_targets=='all' else
                sum(hidden_per_player)-hidden_per_player[actor]-queries[actor])
            multiplicity=max(0,multiplicity)
            nodes += multiplicity*child[0]
            leaves += multiplicity*child[1]
            responses += multiplicity*child[2]
        if offers[actor] < rules.offer_limit:
            used = list(offers); used[actor] += 1; used = tuple(used)
            reject = count(turn+1, masks, queries, used)
            for partner in range(n):
                if partner == actor:
                    continue
                options = []
                for p in (actor,partner):
                    remaining = allmasks[p] ^ masks[p]
                    options.append([0]+[1<<a for a in range(spec.n_actions_per_player[p])
                                        if remaining & (1<<a)])
                for own, other in product(*options):
                    if own == other == 0:
                        continue
                    updated = list(masks); updated[actor] |= own; updated[partner] |= other
                    accept = count(turn+1, tuple(updated), queries, used)
                    nodes += 1+reject[0]+accept[0]
                    leaves += reject[1]+accept[1]
                    responses += 1+reject[2]+accept[2]
        return nodes, leaves, responses

    nodes, leaves, responses = count(0, (0,)*n, (0,)*n, (0,)*n)
    return dict(public_histories=nodes, terminal_histories=leaves,
        response_histories=responses, cached_physical_states=count.cache_info().currsize,
        worlds=len(rules.worlds), node_world_pairs=nodes*len(rules.worlds))
