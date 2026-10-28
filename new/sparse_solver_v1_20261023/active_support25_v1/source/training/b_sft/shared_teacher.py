"""Common finite-window, information-set teacher for every player.

All private types use one publicly specified policy-solving procedure. Joint
pure policies are improved by information-set best responses, then checked for
profitable unilateral deviations. General-sum convergence is NOT guaranteed;
failure or a resource limit yields no teacher. Windows count completed native
proposal turns, execute a frozen policy, and never use realized private truth
for action selection or expected social tie-breaking.
"""
from dataclasses import dataclass
from itertools import product
from pathlib import Path
import sys
import time
import math
import numpy as np

from training.b_sft.catalogues import validate_catalogues
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'third_party/negotiation_benchmark/src'))
from benac_p.schema import GameSpec,Goal,ActionRef
from benac_p.endgame import Endgame,Node,SearchLimit
from benac_p.endgame import fingerprint
from benac_p.endgame_diagnose import decode_action

VERSION='shared-information-set-window-v1'
TOL=1e-9


def specification(turns=2):
    return dict(version=VERSION,window_proposal_turns=turns,
        players='Every player uses the same frozen, public contingent policy solution, conditioned only on its own preference row and public history.',
        objective='Lexicographic: maximize expected own window-end goal utility; among exact own-value ties maximize expected sum of other players goal utilities under the acting player information.',
        horizon='Plan and execute the whole public window, then re-solve. A nonterminal window-end goal score is a bounded evaluation, NOT terminal Q or an equilibrium of the original full game.',
        solution='Deterministic information-set best-response sweeps; reject unless no profitable unilateral own-type-conditioned deviation remains within the window. No guarantee a pure fixed point exists.',
        solution_selection='Initialize every contingent action to the first native legal action; sweep players in increasing player ID order. Require a stable entire contingent policy and verify each private type against its complete best response. This public selection convention is not a uniqueness claim.',
        off_path='Unreachable counterfactual information sets use the window-start prior conditioned on own type. Actual histories with zero likelihood are rejected, not silently reset.',
        ties='After own and other-player value ties, native action order. Residual ties are recorded separately.',
        prior='Uniform over surviving unique joint worlds. Public actions filter by the exact frozen policy; own private information further conditions each player belief.')


def native(raw, *, allow_linear=False):
    validate_catalogues(raw);g=raw['game']
    if not allow_linear and any(not x.get('binary',True) for x in g['goals']):raise ValueError('Binary reference only')
    goals=tuple(Goal(x['goal_id'],tuple(ActionRef(**a) for a in x['required_actions']),x.get('binary',True)) for x in g['goals'])
    spec=GameSpec(g['n_players'],tuple(g['n_actions_per_player']),goals,
        np.zeros((g['n_players'],len(goals)),dtype=np.int8),tuple(g['round_robin']),g['max_changes'],0,
        forbidden_actions=None if g.get('forbidden_actions') is None else np.array(g['forbidden_actions']),menu_enabled=g.get('menu_enabled',False))
    types={int(p):tuple(tuple(row) for row in rows) for p,rows in raw['type_catalogues'].items()}
    # Endgame supplies native legality/state transitions only. Its old partner
    # kernel and its best-response value search are never invoked here.
    def forbidden_kernel(_):raise AssertionError('Old partner kernel must not be called')
    rules=Endgame(spec,raw['ego'],raw['own_preferences'],{p:r for p,r in types.items() if p!=raw['ego']},forbidden_kernel)
    return rules,tuple(product(*(types[p] for p in range(spec.n_players)))),types


@dataclass
class Entry:
    node: object
    actor: object
    actions: tuple
    children: tuple
    payoff: object=None


class SharedWindow:
    def __init__(self,rules,root,worlds,turns=2,max_nodes=60000,max_sweeps=16,seconds=30):
        if any(not isinstance(x,int) or isinstance(x,bool) or x<=0 for x in (turns,max_nodes,max_sweeps)) or not math.isfinite(seconds) or seconds<=0:
            raise ValueError('Positive integer tree/window/sweep budgets and finite positive seconds required')
        self.rules=rules;self.worlds=tuple(worlds);self.types=np.array(worlds,dtype=float)
        if not self.worlds or len(set(self.worlds))!=len(self.worlds):raise ValueError('Nonempty unique worlds required')
        self.n=rules.spec.n_players;self.w=len(worlds);self.end=min(len(rules.spec.round_robin),root.state.turn_index+turns)
        self.max_nodes=max_nodes;self.max_sweeps=max_sweeps;self.deadline=time.monotonic()+seconds
        self.entries=[];self.leaves={};self.groups={}
        for p in range(self.n):
            self.groups[p]=[np.array([i for i,w in enumerate(worlds) if w[p]==row],dtype=int) for row in dict.fromkeys(w[p] for w in worlds)]
        self._grow(Node(root.state,self.worlds,root.pending))
        self.policy=[None if e.actor is None else np.zeros(self.w,dtype=int) for e in self.entries]
        self.certificate=None;self.values=None

    def _check(self):
        if time.monotonic()>self.deadline:raise SearchLimit('Shared teacher wall budget exceeded')

    def _grow(self,node):
        self._check()
        if len(self.entries)>=self.max_nodes:raise SearchLimit('Shared teacher public-tree node budget exceeded')
        index=len(self.entries);self.entries.append(None)
        if node.state.is_terminal or node.state.turn_index>=self.end:
            key=node.state.snapshot_commitments()
            if key not in self.leaves:self.leaves[key]=np.einsum('wpg,g->wp',self.types,node.state.goal_satisfaction())
            self.entries[index]=Entry(node,None,(),(),self.leaves[key]);return index
        actions=self.rules.actions(node)
        children=tuple(self._grow(self.rules._apply(node,a)) for a in actions)
        self.entries[index]=Entry(node,self.rules.actor(node),actions,children)
        return index

    def evaluate(self,policy=None):
        policy=self.policy if policy is None else policy;values=[None]*len(self.entries);wi=np.arange(self.w)
        for i in reversed(range(len(self.entries))):
            if i%256==0:self._check()
            e=self.entries[i]
            values[i]=e.payoff if e.actor is None else np.stack([values[c] for c in e.children])[policy[i],wi,:]
        return values

    def response(self,player):
        """Exact pure best response in this finite tree, with private info grouped.

        Counterfactual reach ignores the responding player's past actions,
        permitting complete unilateral policies rather than one-step deviations.
        """
        reach=[None]*len(self.entries);reach[0]=np.ones(self.w)
        for i,e in enumerate(self.entries):
            if i%256==0:self._check()
            for a,c in enumerate(e.children):reach[c]=reach[i] if e.actor==player else reach[i]*(self.policy[i]==a)
        values=[None]*len(self.entries);updates={};wi=np.arange(self.w)
        for i in reversed(range(len(self.entries))):
            if i%256==0:self._check()
            e=self.entries[i]
            if e.actor is None:values[i]=e.payoff;continue
            av=np.stack([values[c] for c in e.children])
            if e.actor!=player:values[i]=av[self.policy[i],wi,:];continue
            choices=np.zeros(self.w,dtype=int)
            for ids in self.groups[player]:
                weights=reach[i][ids]
                if weights.sum()==0:weights=np.ones(len(ids))
                means=np.einsum('awp,w->ap',av[:,ids,:],weights/weights.sum())
                own=means[:,player];others=means.sum(axis=1)-own
                first=np.flatnonzero(own>=own.max()-TOL)
                final=first[others[first]>=others[first].max()-TOL]
                choices[ids]=int(final[0])
            updates[i]=choices;values[i]=av[choices,wi,:]
        return updates,values[0]

    def solve(self):
        seen=set()
        for sweep in range(self.max_sweeps):
            self._check();changed=0
            for p in range(self.n):
                updates,_=self.response(p)
                for i,new in updates.items():
                    changed+=int(np.count_nonzero(self.policy[i]!=new));self.policy[i]=new
            values=self.evaluate();checks=[];valid=True
            for p in range(self.n):
                _,br=self.response(p)
                for ids in self.groups[p]:
                    base=values[0][ids].mean(axis=0);alternative=br[ids].mean(axis=0)
                    own=float(alternative[p]-base[p]);social=float((alternative.sum()-alternative[p])-(base.sum()-base[p]))
                    if own>TOL or abs(own)<=TOL and social>TOL:valid=False
                    checks.append(dict(player=p,own_type=list(self.worlds[int(ids[0])][p]),own_gain=own,others_gain=social))
            # A root certificate alone can preserve empty coordination policies.
            # Require a stable full contingent table, including off-path choices.
            if valid and changed==0:
                self.values=values;self.certificate=dict(verified=True,sweeps=sweep+1,nodes=len(self.entries),
                    type_checks=checks,max_own_deviation_gain=max(x['own_gain'] for x in checks),
                    scope='Finite window only, pure policy fixed point and conditional unilateral-deviation check; not full-game optimality.')
                return self
            key=b''.join(x.tobytes() for x in self.policy if x is not None)
            if key in seen:raise SearchLimit('Shared teacher pure-policy iteration cycled; no certified label')
            seen.add(key)
        raise SearchLimit('Shared teacher did not reach a certified fixed point within sweep budget')

    def action(self,index,own):
        if self.certificate is None:raise ValueError('Solve and certify before using a policy')
        e=self.entries[index]
        ids=[i for i,w in enumerate(self.worlds) if w[e.actor]==tuple(own)]
        if not ids:raise ValueError('Own type outside public catalogue')
        choices={int(self.policy[index][i]) for i in ids}
        if len(choices)!=1:raise AssertionError('Private truth leaked into information-set action')
        return e.actions[choices.pop()]

    def labels(self,index,possible,player,own):
        """Teacher-only one-action continuation values under the SAME frozen profile."""
        e=self.entries[index]
        if e.actor!=player:raise ValueError('Label only the actual acting player')
        ids=[i for i in possible if self.worlds[i][player]==tuple(own)]
        if not ids:raise ValueError('Empty information set')
        values=np.array([self.values[c][ids].mean(axis=0) for c in e.children]);primary=values[:,player]
        social=values.sum(axis=1)-primary;best=np.flatnonzero(primary>=primary.max()-TOL)
        final=best[social[best]>=social[best].max()-TOL]
        chosen=e.actions.index(self.action(index,own))
        if chosen not in final:raise ValueError('On-path action failed sequential value check')
        return dict(actions=[dict(action=a.to_dict(),own=float(primary[i]),others=float(social[i])) for i,a in enumerate(e.actions)],
            own_optimal_actions=[e.actions[int(i)].to_dict() for i in best],
            social_optimal_actions=[e.actions[int(i)].to_dict() for i in final],
            selected=e.actions[chosen].to_dict(),prosocial_tie_resolved=len(final)<len(best),residual_tie=len(final)>1,
            terminal_value=self.end==len(self.rules.spec.round_robin),
            scope='Expected window-end utility after this action, then the same frozen shared policy; not unrestricted terminal best response.')


class IncompatibleHistory(ValueError):pass


class SharedGame:
    """Public belief and frozen window execution; no special greedy partner role."""
    def __init__(self,raw,**budgets):
        declared=raw.get('teacher_model')
        if declared is not None and (declared.get('version')!=VERSION or declared.get('window_proposal_turns')!=budgets.get('turns',2)):
            raise ValueError('Declared teacher version/window does not match requested shared solver')
        self.raw=raw;self.rules,self.worlds,self.catalogues=native(raw);self.budgets=budgets;self.windows={};self.failures={}

    def window(self,node,worlds):
        key=(fingerprint(node.state.public_state()),None if node.pending is None else fingerprint(node.pending.to_dict()),worlds)
        if key in self.failures:raise SearchLimit(self.failures[key])
        if key not in self.windows:
            try:self.windows[key]=SharedWindow(self.rules,node,worlds,**self.budgets).solve()
            except SearchLimit as exc:self.failures[key]=str(exc);raise
        return self.windows[key]

    def start(self):
        t=self.window(self.rules.initial(),self.worlds)
        return t,0,tuple(range(len(t.worlds)))

    def advance(self,position,action):
        t,index,possible=position;e=t.entries[index]
        if action not in e.actions:raise IncompatibleHistory('History includes an illegal native action')
        ai=e.actions.index(action);remaining=tuple(i for i in possible if int(t.policy[index][i])==ai)
        if not remaining:raise IncompatibleHistory('Observed action has zero likelihood under the new shared policy; do not reuse old B/P labels')
        child=e.children[ai];node=t.entries[child].node
        if t.entries[child].actor is None and not node.state.is_terminal:
            worlds=tuple(t.worlds[i] for i in remaining);next_tree=self.window(node,worlds)
            return next_tree,0,tuple(range(len(worlds)))
        return t,child,remaining

    def replay(self,history):
        position=self.start()
        for index,a in enumerate(history):
            try:position=self.advance(position,decode_action(a))
            except IncompatibleHistory as exc:raise IncompatibleHistory(f'Event {index+1}: {exc}') from exc
        return position

    def belief(self,position,player,own):
        from training.b_sft.favored_belief import marginal
        from training.b_sft.social_rollout import queries_for
        t,_,possible=position
        worlds=tuple(t.worlds[i] for i in possible if t.worlds[i][player]==tuple(own))
        if not worlds:raise ValueError('Own information incompatible with public observations')
        return [dict(**q,**marginal(worlds,q['player'],q['goal'])) for q in queries_for(self.catalogues,player)]

    def payload(self,position,player,own,history):
        t,i,_=position;e=t.entries[i]
        if e.actor!=player:raise ValueError('Only the acting player receives a decision prompt')
        from training.b_sft.social_rollout import queries_for
        return dict(player=player,own_preferences=list(own),game=self.rules.spec.to_dict(include_private=False),
            public_state=e.node.state.public_state(),pending_offer=None if e.node.pending is None else e.node.pending.to_dict(),
            history=history,public_type_catalogues=self.catalogues,queries=queries_for(self.catalogues,player),
            teacher_model=specification(self.budgets.get('turns',2)),
            legal_actions=[a.to_dict() for a in e.actions],
            instruction='Judge all listed hidden preferences using visible history and your own goals; output possible_preferences and favored or undetermined, without counts or probabilities. Select a native action; use your own B output and history for planning.')

    def evidence(self,position,action):
        """Separate self-value, prosocial, and remaining native-order exclusions.

        Relaxing a tie only at this event is a local diagnostic. It does not
        replace the declared frozen policy or invent a new global posterior.
        """
        t,index,possible=position;p=t.entries[index].actor;by_type={};counts=dict(strict_self_value=0,prosocial_tie_rule=0,residual_native_order=0,retained=0)
        for wi in possible:
            own=t.worlds[wi][p]
            if own not in by_type:by_type[own]=t.labels(index,possible,p,own)
            label=by_type[own];a=action.to_dict()
            if a==label['selected']:counts['retained']+=1
            elif a in label['social_optimal_actions']:counts['residual_native_order']+=1
            elif a in label['own_optimal_actions']:counts['prosocial_tie_rule']+=1
            else:counts['strict_self_value']+=1
        return dict(public_worlds_before=len(possible),public_worlds_after=counts['retained'],exclusion_reasons=counts,
            scope='Local observed-action diagnostic under the same frozen continuation; residual native-order exclusions are not goal-based evidence.')

    def episode(self,world):
        if world not in self.worlds:raise ValueError('Actual world outside public catalogue')
        position=self.start();history=[];records=[]
        while True:
            t,index,possible=position;e=t.entries[index]
            if e.node.state.is_terminal:
                utility=np.array(world)@e.node.state.goal_satisfaction()
                return dict(status='terminal',history=history,records=records,utilities=utility.tolist(),
                    policy=VERSION,training_ready=False)
            p=e.actor;own=world[p];b=self.belief(position,p,own)
            label=t.labels(index,possible,p,own);action=t.action(index,own)
            records.append(dict(input=self.payload(position,p,own,history[:]),B=b,P=label,
                evidence_after_action=self.evidence(position,action),
                public_worlds=len(possible),window_end=t.end,certificate=t.certificate,
                note='Reference policy trace, not LM on-policy data; B/P values remain teacher-side.'))
            history.append(action.to_dict());position=self.advance(position,action)
