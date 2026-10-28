"""Certified, deterministic, information-limited BENAC diagnostic subgames.

The public protocol restricts each stage's offer catalogue. This is a selected
three-turn task family, not the unrestricted BENAC population. Every offer is
validated and executed by GameState. Partner optimality is certified against
all allowed future ego actions, not assumed from a myopic heuristic.
"""
from dataclasses import dataclass
import numpy as np
from benac_p.schema import GameSpec, Goal, ActionRef, Offer, MenuOffer, OfferProposal, PassProposal, response_actions
from benac_p.state import GameState

PREFERENCES = ('want', 'neutral', 'avoid')
VERSION = 'semantic-rational-game-v1'


@dataclass(frozen=True)
class Move:
    key: str
    text: str
    action: object


class SemanticGame:
    def __init__(self, seed, condition='unknown_relevant', known=None):
        if condition not in ('unknown_relevant','known','unknown_irrelevant'):
            raise ValueError('Unknown semantic condition')
        self.seed, self.condition = seed, condition
        rng = np.random.default_rng(seed)
        words = ['Cedar','Harbor','Orchid','Maple','Quartz','Willow','Coral','Meadow','Birch']
        self.names = tuple(str(x) for x in rng.choice(words,3,replace=False))
        self.route_for_type = dict(zip(PREFERENCES, rng.permutation(3).tolist()))
        self.known = known or PREFERENCES[seed % 3]
        self.support = (self.known,) if condition == 'known' else PREFERENCES
        # A0 assessment, A1:4 routes, A4 route permit, A5 preparation, A6 neutral note.
        # P1: assessment options C0/C1, permit C2, preparation C3; P2: route approvals.
        self.milestones = int(rng.integers(4,8))
        self.burden = int(rng.integers(1,3))
        self.preparation = int(rng.integers(1,3))
        # Certify a positive information value without inspecting LLM outputs.
        if 2*(self.milestones-self.burden) <= 3*self.preparation:
            self.preparation = 1
        requirements=[]; owners=[]
        for option in range(2):
            for extra in range(self.burden):
                requirements.append(((0,0),(1,option))+(((0,7),) if extra else ()))
                owners.append(('assessment',option))
        requirements.append(((0,4),(1,2)));owners.append(('permit',0))
        for extra in range(self.preparation):
            requirements.append(((0,5),(1,3))+(((0,7),) if extra else ()))
            owners.append(('preparation',0))
        for r in range(3):
            requirements.append(((0,1+r),(2,r)));owners.append(('approval',r))
            # Distinct three-party conjunctions of already bound route,
            # permit and registration commitments; no duplicate goals.
            from itertools import combinations
            ego_refs=((0,1+r),(0,4),(0,7))
            variants=[v for k in (1,2,3) for v in combinations(ego_refs,k)]
            for refs in variants[:self.milestones]:
                requirements.append(tuple(refs)+((1,2),(2,r)));owners.append(('milestone',r))
        goals=tuple(Goal(i,tuple(ActionRef(*x) for x in req)) for i,req in enumerate(requirements))
        self.rows={}
        for pref in PREFERENCES:
            ego=[];p1=[];p2=[]
            sign=dict(want=1,neutral=0,avoid=-1)[pref]
            for kind,r in owners:
                ego.append(-1 if kind=='assessment' else int(kind in ('preparation','milestone')))
                p1.append((sign if r==0 else -sign) if kind=='assessment' else int(kind in ('permit','preparation')))
                p2.append((1 if condition=='unknown_irrelevant' or r==self.route_for_type[pref] else -1) if kind=='approval' else 0)
            self.rows[pref]=(ego,p1,p2)
        self.spec=GameSpec(3,(8,4,3),goals,np.array(self.rows[self.support[0]]),(0,0,0),2,seed,menu_enabled=True)
        self._q_cache={}
        self._cert_cache = {}

    def initial(self):
        state = GameState(self.spec)
        state.commitments[0,7] = 1
        return state

    def offer(self,state,partner,ego_add=(),partner_add=()):
        e=list(state._row_tuple(0));p=list(state._row_tuple(partner))
        for i in ego_add:e[i]=1
        for i in partner_add:p[i]=1
        return Offer(partner,tuple(e),tuple(p))

    def moves(self,state):
        if state.turn_index == 0:
            left=self.offer(state,1,(0,),(0,));right=self.offer(state,1,(0,),(1,))
            prep=self.offer(state,1,(5,),(3,));note=self.offer(state,1,(5,6),(3,))
            ra=self.route_for_type['avoid'];rb=self.route_for_type['want']
            locked_left=self.offer(state,1,(0,1+ra),(0,))
            locked_right=self.offer(state,1,(0,1+rb),(1,))
            moves=[Move('wait','Skip the preliminary interaction.',PassProposal()),
                   Move('prepare','Offer joint preparation: complete the extra preparation goal.',OfferProposal(prep)),
                   Move('assess_a','Offer the first assessment alone.',OfferProposal(left)),
                   Move('assess_b','Offer the second assessment alone.',OfferProposal(right)),
                   Move('assess_menu','Offer a menu: first assessment OR second assessment.',OfferProposal(MenuOffer((left,right)))),
                   Move('committing_menu',f'Offer a binding menu: first assessment AND lock {self.names[ra]} route; OR second assessment AND lock {self.names[rb]} route. The selected route cannot later be changed.',OfferProposal(MenuOffer((locked_left,locked_right)))),
                   Move('prepare_menu','Offer a menu: preparation OR preparation with an inconsequential note.',OfferProposal(MenuOffer((prep,note))))]
        elif state.turn_index == 1:
            bound=[r for r in range(3) if state.commitments[0,1+r]]
            if len(bound)>1:raise ValueError('Multiple routes violate the public protocol.')
            available=bound or list(range(3))
            offers={r:self.offer(state,1,(4,1+r),(2,)) for r in available}
            moves=[Move(f'route_{r}',f'Bind the {self.names[r]} route and obtain the route permit.',OfferProposal(o)) for r,o in offers.items()]
            moves += [Move(f'route_menu_{a}_{b}',f'Offer P1 a route menu: {self.names[a]} first, {self.names[b]} second. Only the chosen route is bound.',OfferProposal(MenuOffer((offers[a],offers[b])))) for a,b in ((0,1),(1,2),(2,0)) if a in offers and b in offers]
        elif state.turn_index == 2:
            routes=[r for r in range(3) if state.commitments[0,1+r]]
            if len(routes)!=1:raise ValueError('Protocol requires exactly one bound route.')
            r=routes[0]
            moves=[Move('approval',f'Request P2 approval of the bound {self.names[r]} route.',OfferProposal(self.offer(state,2,(),(r,))))]
        else:return ()
        for m in moves:
            if isinstance(m.action,OfferProposal):state.validate_offer(m.action.offer)
        # Display order changes across fixtures, never according to correct answer.
        order=np.random.default_rng(self.seed+state.turn_index*701).permutation(len(moves))
        return tuple(moves[i] for i in order)

    def _utility(self,state,player,own_preferences):
        return sum(v for g,v in zip(self.spec.goals,own_preferences) if all(state.commitments[a.player_id,a.action_id] for a in g.required_actions))

    def response(self,state,move,own_preferences):
        """Only the responder's own row and public commitments enter selection.

        Certificates below prove that these snapshot rankings coincide with
        terminal rankings for EVERY allowed continuation (future permit utility
        is an identical constant across root responses). No hidden row is read.
        """
        if isinstance(move.action,PassProposal):return None
        offer=move.action.offer;player=offer.partner_id
        candidates=[]
        for response in response_actions(offer):
            child=state.clone();child.resolve_offer(offer,response)
            candidates.append((self._utility(child,player,own_preferences),response.value))
        best=max(x[0] for x in candidates)
        # Public tie rule: reject before an equally good agreement; option 1 before 2.
        return next(r for value,r in candidates if value==best)

    def execute(self,state,move,pref):
        if isinstance(move.action,PassProposal):
            child=state.clone();child.apply_pass();return None,child
        player=move.action.offer.partner_id
        response=self.response(state,move,self.rows[pref][player])
        child=state.clone();child.resolve_offer(move.action.offer,response)
        return response,child

    def branches(self,state,support,move):
        grouped={}
        for pref in support:
            response,child=self.execute(state,move,pref)
            grouped.setdefault(response,dict(response=response,state=child,support=[],weight=0.))
            grouped[response]['support'].append(pref)
            grouped[response]['weight']+=1/len(support)
        return tuple(dict(b,support=tuple(b['support'])) for b in grouped.values())

    def q_values(self,state,support):
        if not support:raise ValueError('Empty preference support')
        if state.is_terminal:return ()
        key=(state.turn_index,state.snapshot_commitments(),tuple(sorted(support)))
        if key in self._q_cache:return self._q_cache[key]
        values=[]
        for move in self.moves(state):
            value=0.
            for branch in self.branches(state,support,move):
                child=branch['state']
                continuation=self._utility(child,0,self.rows[PREFERENCES[0]][0]) if child.is_terminal else max(v for _,v in self.q_values(child,branch['support']))
                value+=branch['weight']*continuation
            values.append((move,float(value)))
        self._q_cache[key]=tuple(values)
        return self._q_cache[key]

    def optimal(self,state,support):
        values=self.q_values(state,support);best=max(v for _,v in values)
        return tuple(m for m,v in values if abs(v-best)<1e-9)

    def _terminal_own_values(self,state,pref,player):
        if state.is_terminal:return {self._utility(state,player,self.rows[pref][player])}
        values=set()
        for m in self.moves(state):
            _,child=self.execute(state,m,pref)
            values.update(self._terminal_own_values(child,pref,player))
        return values

    def certify_response(self,state,move,pref):
        if isinstance(move.action,PassProposal):return
        key=(state.turn_index,state.snapshot_commitments(),move.key,pref)
        if key in self._cert_cache:return
        player=move.action.offer.partner_id;values={}
        for response in response_actions(move.action.offer):
            child=state.clone();child.resolve_offer(move.action.offer,response)
            # A rejected mandatory route permit is followed by termination. It is
            # strictly dominated: accepting gives P1 its wanted permit goal.
            if state.turn_index==1 and response.value=='REJECT':
                vals={self._utility(child,player,self.rows[pref][player])}
            else:vals=self._terminal_own_values(child,pref,player)
            if len(vals)!=1:raise AssertionError('Partner value depends on future ego choices; reject this instance.')
            values[response.value]=next(iter(vals))
        best=max(values.values());expected=next(r for r,v in values.items() if v==best)
        actual=self.response(state,move,self.rows[pref][player])
        if actual!=expected:raise AssertionError('Snapshot response is not terminal optimal.')
        self._cert_cache[key]=values

    def certify(self):
        def walk(state,pref):
            if state.is_terminal:return
            for move in self.moves(state):
                self.certify_response(state,move,pref)
                _,child=self.execute(state,move,pref)
                walk(child,pref)
        for pref in PREFERENCES:walk(self.initial(),pref)
        root=self.initial();q={m.key:v for m,v in self.q_values(root,self.support)}
        menu=q['assess_menu'];best=max(q.values())
        if self.condition=='unknown_relevant':
            if not menu>q['prepare']+1e-8 or abs(menu-best)>1e-8:raise AssertionError('Information opportunity not useful.')
        elif not q['prepare']>menu+1e-8:raise AssertionError('Control does not change action value.')
        menu_move=next(m for m in self.moves(root) if m.key=='assess_menu')
        frozen=0.
        for branch in self.branches(root,self.support,menu_move):
            chosen=self.optimal(branch['state'],self.support)[0]
            actual=dict((m.key,v) for m,v in self.q_values(branch['state'],branch['support']))
            frozen+=branch['weight']*actual[chosen.key]
        update_gain=menu-frozen
        if self.condition=='unknown_relevant' and update_gain<=0:
            raise AssertionError('Same-action evidence update has no task value.')
        return dict(version=VERSION,condition=self.condition,milestones=self.milestones,burden=self.burden,preparation=self.preparation,root_q=q,optimal_actions=[m.key for m in self.optimal(root,self.support)],
                    same_menu_judgment_update_gain=update_gain,
                    rational_response_decisions=len(self._cert_cache),all_terminal_response_values_continuation_invariant=True,
                    public_equal_frequency_support=list(self.support),partner_behavior_randomness=False,
                    selection='Certified three-stage protocol family; not unrestricted BENAC failure prevalence.')

    def description(self):
        profiles=[]
        for pref in PREFERENCES:
            other=dict(want='avoid',neutral='neutral',avoid='want')[pref]
            approval='wants approval of every route' if self.condition=='unknown_irrelevant' else f'wants approval of {self.names[self.route_for_type[pref]]} and avoids approval of either other route'
            profiles.append(dict(first_assessment=pref,second_assessment=other,P2=approval))
        return dict(players=['P0 (you)','P1 (assessment and permit partner)','P2 (approval partner)'],
            protocol=[
                f'Stage 1: choose one listed preliminary proposal to P1, or skip. Accepted assessment creates {self.burden} AVOID administrative burdens for you. Accepted preparation completes {self.preparation} extra WANT goals. Rejection binds nothing.',
                'Stage 2: offer P1 exactly one listed route proposal or route menu. A route already bound by a preliminary menu cannot be changed: only its permit proposal remains available. Otherwise the accepted choice irreversibly binds a route and the common permit. If P1 rejects the permit, the project ends without milestones.',
                'Stage 3: automatically request P2 approval of the already bound route. Routing cannot be amended at this stage. P2 accepts or rejects, then the game ends.'],
            outcome=f'Approval with the route permit completes {self.milestones} equally weighted WANT project milestones for you, each requiring commitments from all three players. Preparation adds {self.preparation} WANT goals. Each accepted assessment adds {self.burden} AVOID burdens. Other goals are NEUTRAL to you. WANT contributes positively, AVOID negatively, with equal per-goal magnitude.',
            partner_rules='Partners maximize their own terminal utility, not yours. P1 always wants preparation and the common route permit; P1 is neutral to project milestones and P2 approvals. P2 is neutral to all goals except its route approvals. Rejection is preferred to an equally valuable agreement; among equally valuable accepted menu options, the earlier option is selected. Partners never act randomly.',
            preference_configurations=profiles,
            population='The three configurations occur equally often before evidence. After observing deterministic responses, each configuration still consistent with the evidence remains equally represented. Your own proposals are not evidence.',
            offered_actions='Only the listed proposals at each stage are available in this controlled protocol. All are ordinary legal BENAC proposals; each chosen menu option immediately binds its commitments.')

    def judgment(self,support):
        return dict(partner='P1',goal='first assessment',possible_preferences=[p for p in PREFERENCES if p in support])

    def observed_event(self,move,response):
        return dict(proposal=move.text,response=response or 'NO_RESPONSE',
                    response_meaning={'CHOOSE_1':'First menu option chosen; only that option binds.','CHOOSE_2':'Second menu option chosen; only that option binds.','ACCEPT':'The offer binds.','REJECT':'No proposed commitments bind.'}.get(response,'No proposal was made.'))
