from copy import deepcopy
from itertools import product
from pathlib import Path
import json
import unittest
import numpy as np

from training.b_sft.shared_teacher import native,SharedWindow,SharedGame,SearchLimit,IncompatibleHistory,specification
from benac_p.schema import Offer,OfferProposal,ResponseAction


def response_fixture(avoid=False,uncertain=False):
    own=[1,-1 if avoid else 0,0]
    raw=dict(ego=0,game=dict(n_players=3,n_actions_per_player=[1]*3,
        goals=[dict(goal_id=i,binary=True,required_actions=[dict(player_id=p,action_id=0) for p in ps]) for i,ps in enumerate([(0,2),(0,1),(1,2)])],
        round_robin=[0,1,2],max_changes=1,menu_enabled=False),own_preferences=own,
        type_catalogues={'0':[own],'1':[[0,1,0]],'2':[[0,1,1],[0,-1,1]] if uncertain else [[0,1,1]]},history=[])
    rules,worlds,_=native(raw);node=rules.initial()
    for a in [OfferProposal(Offer(1,(1,),(0,))),ResponseAction('ACCEPT'),OfferProposal(Offer(0,(1,),(1,)))]:node=rules._apply(node,a)
    return raw,rules,node,worlds


class SharedTeacherTests(unittest.TestCase):
    def test_prosocial_tie_but_never_sacrifice_own_utility(self):
        for avoid,expected in [(False,'ACCEPT'),(True,'REJECT')]:
            raw,r,n,w=response_fixture(avoid);t=SharedWindow(r,n,w,turns=1).solve()
            labels=t.labels(0,(0,),0,raw['own_preferences'])
            self.assertEqual(labels['selected'],{'response':expected})
            self.assertEqual(labels['prosocial_tie_resolved'],not avoid)
            self.assertEqual(t.certificate['max_own_deviation_gain'],0)

    def test_other_payoff_is_expected_not_realized_private_truth(self):
        raw,r,n,w=response_fixture(uncertain=True);t=SharedWindow(r,n,w,turns=1).solve()
        labels=t.labels(0,tuple(range(len(w))),0,raw['own_preferences'])
        accept=next(x for x in labels['actions'] if x['action']=={'response':'ACCEPT'})
        self.assertEqual(accept['others'],1.)  # actual totals can be 0 or 2
        self.assertEqual(accept['own'],0.)
        self.assertEqual(len(set(t.policy[0])),1)

    def test_independent_exhaustive_unilateral_policy_check(self):
        raw,r,n,w=response_fixture(uncertain=True);t=SharedWindow(r,n,w,turns=1).solve()
        # Direct leaf evaluation, independent of response()/evaluate().
        for choice in range(len(t.entries[0].actions)):
            child=r._apply(n,t.entries[0].actions[choice]);pay=np.array(w)@child.state.goal_satisfaction()
            primary=pay[:,0].mean();other=(pay.sum(axis=1)-pay[:,0]).mean()
            chosen=t.labels(0,tuple(range(len(w))),0,raw['own_preferences'])
            best=next(x for x in chosen['actions'] if x['action']==chosen['selected'])
            self.assertLessEqual(primary,best['own']+1e-9)
            if primary==best['own']:self.assertLessEqual(other,best['others']+1e-9)

    def test_budget_failure_never_yields_a_label(self):
        _,r,n,w=response_fixture()
        with self.assertRaises(SearchLimit):SharedWindow(r,n,w,max_nodes=1)
        t=SharedWindow(r,n,w)
        with self.assertRaisesRegex(ValueError,'certify'):t.action(0,w[0][0])

    def test_teacher_version_cannot_silently_mix(self):
        from training.b_sft.social_rollout import build
        raw,_,_,_=response_fixture();raw['teacher_model']=specification(2)
        with self.assertRaisesRegex(ValueError,'legacy'):build(raw,3000)
        with self.assertRaisesRegex(ValueError,'does not match'):SharedGame(raw,turns=3)

    def test_exhaustive_contingent_policy_deviations(self):
        raw,r,_,w=response_fixture(uncertain=True)
        t=SharedWindow(r,r.initial(),w,turns=1).solve()
        def outcome(world_index,player,replacements):
            i=0;world=w[world_index]
            while t.entries[i].actor is not None:
                e=t.entries[i];key=(i,world[e.actor])
                a=replacements[key] if e.actor==player else e.actions.index(t.action(i,world[e.actor]))
                i=e.children[a]
            return np.array(world)@t.entries[i].node.state.goal_satisfaction()
        for player in range(3):
            keys=[(i,row) for i,e in enumerate(t.entries) if e.actor==player for row in dict.fromkeys(x[player] for x in w)]
            counts=[range(len(t.entries[i].actions)) for i,row in keys]
            self.assertLess(np.prod([len(x) for x in counts]),10000)
            original={(i,row):t.entries[i].actions.index(t.action(i,row)) for i,row in keys}
            baseline=np.array([outcome(j,player,original) for j in range(len(w))])
            for choices in product(*counts):
                alternative=dict(zip(keys,choices));pay=np.array([outcome(j,player,alternative) for j in range(len(w))])
                for ids in t.groups[player]:
                    a=pay[ids].mean(axis=0);b=baseline[ids].mean(axis=0)
                    self.assertLessEqual(a[player],b[player]+1e-9)
                    if a[player]==b[player]:self.assertLessEqual(a.sum()-a[player],b.sum()-b[player]+1e-9)

    def test_multiplayer_private_information_and_actual_future_agree(self):
        raw=json.loads((Path(__file__).parent/'fixtures/evidence_switch_regression.json').read_text())['fixture']
        g=SharedGame(raw,turns=2);episodes=[g.episode(w) for w in g.worlds]
        seen={}
        for episode in episodes:
            self.assertEqual(episode['status'],'terminal')
            for rec in episode['records']:
                inp=rec['input'];key=json.dumps(inp,sort_keys=True)
                if key in seen:self.assertEqual(seen[key],rec['P']['selected'])
                seen[key]=rec['P']['selected']
                self.assertNotIn('environment_world',inp)
                self.assertNotIn('private_preferences',inp['game'])
                pos=g.replay(inp['history']);t,i,possible=pos
                self.assertEqual(t.action(i,inp['own_preferences']).to_dict(),rec['P']['selected'])
                self.assertEqual(g.belief(pos,inp['player'],inp['own_preferences']),rec['B'])
                chosen=t.entries[i].actions.index(t.action(i,inp['own_preferences']))
                ids=[x for x in possible if t.worlds[x][inp['player']]==tuple(inp['own_preferences'])]
                q=t.values[t.entries[i].children[chosen]][ids].mean(axis=0)
                row=next(x for x in rec['P']['actions'] if x['action']==rec['P']['selected'])
                self.assertAlmostEqual(q[inp['player']],row['own'])
        for t in g.windows.values():
            for i,e in enumerate(t.entries):
                if e.actor is None:continue
                for ids in t.groups[e.actor]:self.assertEqual(len(set(t.policy[i][ids])),1)

    def test_independent_trace_audit_rejects_corrupt_b_and_p(self):
        from training.b_sft.shared_teacher_report import verify_traces
        raw=json.loads((Path(__file__).parent/'fixtures/evidence_switch_regression.json').read_text())['fixture']
        g=SharedGame(raw,turns=2);episodes=[]
        for world in g.worlds:
            e=g.episode(world);e['environment_world']=world;episodes.append(e)
        result=verify_traces(raw,episodes)
        self.assertGreater(result['B_queries_checked'],0)
        self.assertGreater(result['P_chosen_predictions_checked'],0)
        bad=deepcopy(episodes);rec=next(r for r in bad[0]['records'] if r['B'])
        rec['B'][0]['answer']['possible_preferences']=[]
        with self.assertRaisesRegex(ValueError,'B fails'):verify_traces(raw,bad)
        bad=deepcopy(episodes);rec=bad[0]['records'][0]
        next(x for x in rec['P']['actions'] if x['action']==rec['P']['selected'])['own']+=1
        with self.assertRaisesRegex(ValueError,'P prediction'):verify_traces(raw,bad)


if __name__=='__main__':unittest.main()
