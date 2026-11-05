"""Analytic signaling examples: no INVESTIGATE action or query-answer channel."""
import unittest
from types import SimpleNamespace as NS
import numpy as np
from .behavior_information import public_behavior_value, public_history_value

class Action:
    def __init__(self,name):self.name=name
    def to_dict(self):return {'action':self.name}


def signaling(reveal=False,noise=False,remember=False):
    worlds=(((1,),(0,)),((1,),(1,)));entries=[];policy={}
    def entry(actor,turn,commit=0,actions=(),children=(),payoff=None):
        i=len(entries)
        state=NS(turn_index=turn,investigation_used=(False,False),transcript=[],snapshot_commitments=lambda:((commit,), (0,)))
        entries.append(NS(actor=actor,node=NS(state=state,pending=None,worlds=worlds),actions=tuple(Action(a) for a in actions),children=children,payoff=payoff))
        if actor is not None:policy[i]=np.full((len(actions),2),1/len(actions))
        return i
    root=entry(0,0,actions=('WAIT',));sender=entry(1,1,actions=('SIGNAL_L','SIGNAL_R'))
    entries[root].children=(sender,);branches=[]
    for signal in range(2):
        if remember:
            mid=entry(0,2,commit=signal,actions=('WAIT',))
        choice=entry(0,3 if remember else 2,commit=signal if reveal else 0,actions=('CHOOSE_L','CHOOSE_R'))
        if remember:entries[mid].children=(choice,)
        branches.append(mid if remember else choice)
        leaves=[]
        for selected in range(2):
            pay=np.zeros((2,2));pay[selected,0]=1.
            leaves.append(entry(None,4,payoff=pay))
        entries[choice].children=tuple(leaves)
    entries[sender].children=tuple(branches)
    policy[sender]=np.full((2,2),.5) if noise else np.eye(2)
    return NS(entries=entries,policy=policy,worlds=worlds,certificate={'verified':True})

class BehaviorInformationTests(unittest.TestCase):
    def metric(self,tree,k=2,weights=(.5,.5),**kwargs):
        return public_behavior_value(tree,ego=0,root_index=0,root_weights=weights,k=k,**kwargs)
    def test_signal_without_investigation_has_positive_value(self):
        r=self.metric(signaling());self.assertAlmostEqual(r['V_full'],1.)
        self.assertAlmostEqual(r['V_restricted'],.5);self.assertAlmostEqual(r['S'],.5)
        self.assertGreater(r['merged_information_cells'],0)
    def test_physical_signal_is_not_falsely_hidden(self):
        self.assertAlmostEqual(self.metric(signaling(reveal=True))['S'],0.)
    def test_uninformative_signal_has_zero_value(self):
        self.assertAlmostEqual(self.metric(signaling(noise=True))['S'],0.)
    def test_nonuniform_prior_and_full_lp_agree_with_analytic_values(self):
        self.assertAlmostEqual(self.metric(signaling(),weights=(.8,.2))['S'],.2)
        self.assertAlmostEqual(self.metric(signaling(),hide_history=False)['S'],0.)
    def test_information_outside_controlled_window_not_counted(self):
        self.assertAlmostEqual(self.metric(signaling(),k=1)['S'],0.)
    def test_remember_previous_physical_observation_after_states_merge(self):
        self.assertAlmostEqual(self.metric(signaling(remember=True),k=3)['S'],0.)
    def test_variable_budget_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError,'variable budget'):
            self.metric(signaling(),max_variables=1)
    def test_selection_opt_in_detects_signal_without_query_and_preserves_default(self):
        from .build import measure_entrance
        tree=signaling();tree.rules=NS(spec=NS(goals=[None]))
        entrance=dict(root_index=0,ego=0,entry_world_weights=[.5,.5])
        config=dict(max_k=2,min_c=.1,min_increment=.05,min_s=.05)
        old,_=measure_entrance(tree,entrance,'signal',config)
        new,_=measure_entrance(tree,entrance,'signal',dict(config,measure_public_behavior=True))
        self.assertTrue(old);self.assertFalse(any(r['information_positive'] for r in old))
        self.assertTrue(any(r['information_positive'] and r['S_query']==0 and r['S_behavior']==.5 for r in new))
    def test_entry_signal_uses_joint_mass_not_equal_weighted_posteriors(self):
        tree=signaling();tree.entries[0].actor=1
        roots=tree.entries[1].children
        r=public_history_value(tree,ego=0,entries=[
            dict(root_index=roots[0],world_masses=[.8,0]),
            dict(root_index=roots[1],world_masses=[0,.2])],k=1)
        self.assertAlmostEqual(r['V_full'],1.)
        self.assertAlmostEqual(r['V_restricted'],.8)
        self.assertAlmostEqual(r['S'],.2)
    def test_entry_mask_cannot_forget_previous_own_action(self):
        tree=signaling();roots=tree.entries[1].children
        with self.assertRaisesRegex(ValueError,'earlier focal'):
            public_history_value(tree,ego=0,entries=[
                dict(root_index=roots[0],world_masses=[.5,0]),
                dict(root_index=roots[1],world_masses=[0,.5])],k=1)

if __name__=='__main__':unittest.main()
