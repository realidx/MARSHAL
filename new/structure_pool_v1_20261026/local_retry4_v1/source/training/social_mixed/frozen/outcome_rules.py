"""Local self-play adapter: native transitions, full public prior, linear goals.
No B/P labels and no modification of the shared teacher implementation.
"""
from functools import lru_cache
from itertools import product
import copy
import numpy as np
from training.social_mixed.frozen.benac_p.schema import GameSpec, Goal, ActionRef
from training.social_mixed.frozen.benac_p.endgame import Endgame
from training.social_mixed.frozen.training.b_sft.social_private_teacher import PrivateInvestigationRules

@lru_cache(maxsize=16)
def support(n, goals, values):
    rows=tuple(r for r in product(values, repeat=goals) if 1 in r)
    worlds=tuple(w for w in product(rows, repeat=n)
                 if all(any(w[p][g] != 0 for p in range(n)) for g in range(goals)))
    return worlds, {p:tuple(dict.fromkeys(w[p] for w in worlds)) for p in range(n)}

def generation_rule(level):
    return dict(version='outcome-public-prior-v1', values=[0,1] if level=='foundation' else [-1,0,1],
        slot_distribution='independent uniform before rejection',
        rejection=['each player wants at least one goal', 'no goal has every player neutral'],
        visibility='Rules are common knowledge. Each player observes its own row; all other rows are hidden. No additional restrictions apply.')

class OutcomeRules(PrivateInvestigationRules):
    def __init__(self, raw):
        g=raw['game']; self.generation=copy.deepcopy(raw['preference_generation'])
        if self.generation != generation_rule('foundation' if self.generation['values']==[0,1] else 'adaptation'):
            raise ValueError('Unknown public preference law')
        if g.get('menu_enabled',False) or raw.get('history'):
            raise ValueError('Self-play starts at zero commitments without MENU')
        goals=tuple(Goal(x['goal_id'],tuple(ActionRef(**a) for a in x['required_actions']),x.get('binary',True)) for x in g['goals'])
        spec=GameSpec(g['n_players'],tuple(g['n_actions_per_player']),goals,
            np.zeros((g['n_players'],len(goals)),dtype=np.int8),tuple(g['round_robin']),g['max_changes'],0,
            forbidden_actions=None if g.get('forbidden_actions') is None else np.array(g['forbidden_actions']),menu_enabled=False)
        self.worlds,self.catalogues=support(spec.n_players,len(goals),tuple(self.generation['values']))
        def forbidden(_): raise AssertionError('Legacy partner solver is not used')
        self.base=Endgame(spec,0,self.catalogues[0][0],{p:r for p,r in self.catalogues.items() if p!=0},forbidden)
        self.spec=self.base.spec

    def public_game(self):
        game=super().public_game()
        game['preference_generation']=copy.deepcopy(self.generation)
        game['reward_rule']='Only your terminal utility: sum of your preference value times goal completion. Binary completion is all requirements; linear completion is the fraction committed. No intermediate or altruism reward.'
        return game

    def observation(self,node,player,own):
        obs=super().observation(node,player,own)
        obs['game']=self.public_game()
        obs['legal_actions']=[a.to_dict() for a in self.actions(node)] if self.actor(node)==player else []
        return obs

from training.social_mixed.frozen.training.b_sft.social_private_teacher import PrivateWindow

class OutcomeWindow(PrivateWindow):
    """Diagnostic own-payoff BR; own ties mix uniformly, without altruism.

    Uses the same full tree, private information partitions and off-path prior.
    Run through audit_solver_cycles.audit, not the B/P solve/certificate method.
    """
    def solve(self):
        raise RuntimeError('Use the local diagnostic audit; no B/P certificate for this objective')

    def response(self, player):
        reach=[None]*len(self.entries);reach[0]=self.world_weights.copy()
        for i,e in enumerate(self.entries):
            if i%256==0:self._check()
            for a,c in enumerate(e.children):reach[c]=reach[i] if e.actor==player else reach[i]*self.policy[i][a]
        values=[None]*len(self.entries);updates={}
        for i in reversed(range(len(self.entries))):
            if i%256==0:self._check()
            e=self.entries[i]
            if e.actor is None:values[i]=e.payoff;continue
            av=np.stack([values[c] for c in e.children])
            if e.actor!=player:
                values[i]=np.einsum('aw,awp->wp',self.policy[i],av);continue
            probs=np.zeros((len(e.actions),self.w))
            for ids in self.information_groups[i]:
                weights=reach[i][ids]
                if weights.sum()==0:weights=self.world_weights[ids]
                own=np.einsum('aw,w->a',av[:,ids,player],weights/weights.sum())
                best=np.flatnonzero(own>=own.max()-1e-9)
                probs[np.ix_(best,ids)]=1/len(best)
            updates[i]=probs;values[i]=np.einsum('aw,awp->wp',probs,av)
        return updates,values[0]
