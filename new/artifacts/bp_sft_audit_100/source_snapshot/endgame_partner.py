"""Information-limited terminal best response to an explicit reference policy.

This is not an equilibrium solver. The reference continuation is deliberately
specified separately from the actual, forward-looking oracle partner.
"""
from dataclasses import replace
from itertools import product
import numpy as np
from benac_p.endgame import Endgame, Node, PartnerDecision, fingerprint
from benac_p.schema import OfferProposal, PassProposal, ResponseAction, Offer, MenuOffer


def transcript_actions(events):
    """Recover separate proposal/response decisions from native public events."""
    result = []
    for event in events:
        if event['action'] == 'PASS':
            result.append(PassProposal())
        else:
            raw = event['offer']
            offer = MenuOffer(tuple(Offer(**o) for o in raw['offers'])) if 'offers' in raw else Offer(**raw)
            result.extend((OfferProposal(offer), ResponseAction(event['response'])))
    return result


def immediate_reference(decision):
    """Deterministic public continuation model, not claimed terminal-optimal.

    Responders maximize currently satisfied own-goal utility (REJECT wins ties).
    Proposers offer their best immediate joint commitment assuming acceptance;
    PASS wins ties. This reference proposes ordinary offers; the terminal best
    responder searches ALL native offers, menus and responses instead.
    """
    public = decision.public_state
    rows = [list(row) for row in public['commitments']]
    def utility(commitments):
        return sum(value for value, goal in zip(decision.own_preferences, public['goals'])
                   if all(commitments[a['player_id']][a['action_id']] for a in goal['required_actions']))
    baseline = utility(rows)
    def accepted_value(offer):
        child = [row[:] for row in rows]
        proposer = public['current_proposer']
        child[proposer] = list(offer.proposer_action)
        child[offer.partner_id] = list(offer.partner_action)
        return utility(child)
    scores = []
    for action in decision.legal_actions:
        if isinstance(action, PassProposal) or action == ResponseAction('REJECT'):
            score = baseline
        elif isinstance(action, ResponseAction):
            raw = decision.pending_offer
            if 'offers' in raw:
                offer = Offer(**raw['offers'][0 if action == ResponseAction('CHOOSE_1') else 1])
            else:
                offer = Offer(**raw)
            score = accepted_value(offer)
        elif isinstance(action.offer, MenuOffer):
            # The fixed reference policy offers no menus; actual oracle does.
            score = -float('inf')
        else:
            score = accepted_value(action.offer)
        scores.append(score)
    return decision.legal_actions[max(range(len(scores)), key=scores.__getitem__)]


class InconsistentPartnerHistory(ValueError):
    """A counterfactual private type has zero likelihood for the public history."""


class RationalPartner:
    """Exact finite-horizon best response under own information.

    Actual histories are filtered using actual oracle actions, recursively at
    strictly shorter prefixes. Learner actions are interventions, not assumed
    rational evidence. Future actions of other players use immediate_reference.
    This distinction is public and appears in exported task specifications.
    """
    VERSION = 'terminal-best-response-to-immediate-reference-v2'

    def __init__(self, spec, type_catalogues, learner=0, max_nodes=20000):
        self.spec = replace(spec, private_preferences=np.zeros_like(spec.private_preferences), seed=0, metadata={})
        self.types = {p: tuple(tuple(row) for row in rows) for p, rows in type_catalogues.items()}
        self.learner, self.max_nodes = learner, max_nodes
        self.cache = {}
        self.labels = {}
        self.searches = {}

    def specification(self):
        return dict(version=self.VERSION, action_randomness=False,
            optimality='Exact expected terminal-utility best response to the stated fixed continuation policy, not an equilibrium or omniscient optimum.',
            future_reference='Other players respond to maximize currently satisfied own-goal utility, rejecting ties. They propose the ordinary offer with greatest own immediate utility assuming acceptance; pass wins ties. Native enumeration breaks remaining ties.',
            history='Infer from actual oracle-player proposals and responses. Learner actions are interventions and do not eliminate preference types.',
            prior='Independent, equally represented public per-player preference catalogues; condition on own row and public evidence.',
            actual_actions='Oracle players search all legal offers, menus, pass, and responses, through the true terminal turn.',
            tie_rule='If the immediate reference action is terminal-optimal, use it; otherwise use the first terminal-optimal action in native enumeration.')

    def __call__(self, decision):
        public_key = dict(decision.public_state)
        key = (decision.player_id, decision.own_preferences,
               fingerprint(public_key), fingerprint(decision.pending_offer))
        if key in self.cache:
            return self.cache[key]
        player = decision.player_id
        # A constant terminal own payoff certifies every native action optimal,
        # independent of unknown types or future behavior. Use the declared tie.
        public=decision.public_state
        free=[(p,a) for p,row in enumerate(public['commitments']) for a,v in enumerate(row) if not v]
        values=set()
        if len(free)<=10:
            for bits in product((0,1),repeat=len(free)):
                rows=[list(row) for row in public['commitments']]
                for (p,a),v in zip(free,bits):rows[p][a]=v
                values.add(sum(v for v,g in zip(decision.own_preferences,public['goals'])
                    if all(rows[a['player_id']][a['action_id']] for a in g['required_actions'])))
                if len(values)>1:break
            if len(values)==1:
                chosen=decision.legal_actions[0]
                self.cache[key]=chosen
                self.labels[key]=dict(best_terminal_value=next(iter(values)),actions=len(decision.legal_actions),
                                      certificate='own terminal payoff constant over every commitment completion')
                return chosen
        search_key = (player, decision.own_preferences)
        if search_key not in self.searches:
            self.searches[search_key] = Endgame(self.spec, player, decision.own_preferences,
                {p: rows for p, rows in self.types.items() if p != player},
                immediate_reference, max_nodes=self.max_nodes,
                max_remaining_turns=len(self.spec.round_robin), markov_partner=True)
        search = self.searches[search_key]
        search.max_nodes = self.max_nodes
        node = search.initial()
        actions = transcript_actions(decision.public_state['transcript'])
        if decision.pending_offer is not None:
            raw = decision.pending_offer
            offer = MenuOffer(tuple(Offer(**o) for o in raw['offers'])) if 'offers' in raw else Offer(**raw)
            actions.append(OfferProposal(offer))
        for action in actions:
            actor = search.actor(node)
            if actor not in (player, self.learner):
                # Use actual policies for the past, not the future reference.
                worlds = tuple(w for w in node.worlds if self(PartnerDecision(
                    actor, node.state.public_state(), w[actor], search.actions(node),
                    None if node.pending is None else node.pending.to_dict())) == action)
                if not worlds:
                    raise InconsistentPartnerHistory('Public history impossible under declared oracle partner policies for this counterfactual type.')
                node = Node(node.state, worlds, node.pending)
            node = search._apply(node, action)
        if node.state.snapshot_commitments() != tuple(tuple(r) for r in decision.public_state['commitments']) or node.state.turn_index != decision.public_state['turn_index']:
            raise ValueError('Public state does not replay from its legal history.')
        q = search.q_values(node)
        best = max(value for _, value in q)
        preferred = immediate_reference(decision)
        chosen = preferred if best-dict(q)[preferred] < 1e-10 else next(action for action, value in q if best-value < 1e-10)
        self.cache[key] = chosen
        self.labels[key] = dict(best_terminal_value=best, actions=len(q), posterior_worlds=len(node.worlds))
        return chosen


class InformationStateRequired(ValueError):
    """The chosen reference-optimal action depends on a missing partner belief."""


class CertifiedMarkovPartner(RationalPartner):
    """Certify one history-free policy attaining every type's reference optimum.

    Solve each possible other-player configuration separately to obtain upper
    bounds. A common optimal action is accepted only if its continuation also
    admits a common optimal policy at every reachable public decision. Thus the
    certified policy achieves those bounds simultaneously and is optimal for any
    posterior over the catalogue. No posterior-subset enumeration is needed.
    """
    VERSION = 'universal-reference-best-response-v2'

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.searches={};self.rejected=set()

    def specification(self):
        result=super().specification()
        result.update(version=self.VERSION,
            information_certificate='A single policy using public commitments/pending offer and own preferences attains the terminal reference-best-response value for every possible other-player type configuration. This is proved recursively through the remaining game. Reject a position if no such policy can be certified.',
            history='The common optimal policy works for every posterior the public history could induce. History therefore is not an additional input needed to predict these selected partners.',
            tie_rule='Among certifiable common optimal actions, maximize the minimum immediate own utility across the public catalogue; remaining ties use native enumeration. This tie rule is independent of posterior beliefs.')
        return result

    def __call__(self,decision):
        public=dict(decision.public_state);public.pop('transcript')
        key=(decision.player_id,decision.own_preferences,fingerprint(public),fingerprint(decision.pending_offer))
        if key in self.cache:return self.cache[key]
        if key in self.rejected:raise InformationStateRequired('No common terminal-optimal reference policy for this physical decision.')
        player=decision.player_id;skey=(player,decision.own_preferences)
        if skey not in self.searches:
            self.searches[skey]=Endgame(self.spec,player,decision.own_preferences,
                {p:rs for p,rs in self.types.items() if p!=player},immediate_reference,
                max_nodes=self.max_nodes,max_remaining_turns=len(self.spec.round_robin),markov_partner=True)
        search=self.searches[skey]
        root=search.initial();root.state.turn_index=public['turn_index']
        for p,row in enumerate(public['commitments']):root.state.commitments[p,:len(row)]=row
        if decision.pending_offer is not None:
            raw=decision.pending_offer
            root.pending=MenuOffer(tuple(Offer(**o) for o in raw['offers'])) if 'offers' in raw else Offer(**raw)
        common=set(search.actions(root));bounds=[]
        for world in search.worlds:
            q=search.q_values(Node(root.state,(world,),root.pending));best=max(v for _,v in q)
            common &= {a for a,v in q if best-v<1e-9};bounds.append(best)
            if not common:break
        def immediate_lower(action):
            child=search._apply(root,action);values=[]
            for world in search.worlds:
                end=child if child.pending is None else search._apply(child,search._partner_action(child,world))
                values.append(float(np.dot(decision.own_preferences,end.state.goal_satisfaction())))
            return min(values)
        candidates=[a for a in search.actions(root) if a in common]
        candidates.sort(key=immediate_lower,reverse=True)  # stable native ties
        for action in candidates:
            try:
                for branch in search.step(root,action):
                    n=branch.node
                    if not n.state.is_terminal:
                        self(type(decision)(player,n.state.public_state(),decision.own_preferences,
                            search.actions(n),None if n.pending is None else n.pending.to_dict()))
            except InformationStateRequired:
                continue
            self.cache[key]=action
            self.labels[key]=dict(configurations_checked=len(search.worlds),reference_terminal_upper_bounds=bounds,
                action=action.to_dict(),certificate='common optimal action with recursively certified common optimal continuation')
            return action
        self.rejected.add(key)
        raise InformationStateRequired('No history-free policy attaining all type-conditioned reference optima; exclude this position.')
