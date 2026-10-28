import copy
import json
from pathlib import Path
import unittest

import numpy as np

from benac_p.schema import OfferProposal
from new.strategic_game_v1_20261021.rules import StrategicRules
from training.b_sft.social_terminal_teacher import Investigate
from training.b_sft.social_private_teacher import observed_slots
from training.strategic_slices.bounded import resolve_horizon
from new.decision_window_v1_20261022.window import DecisionWindow, decision_horizon

POOL = Path(__file__).resolve().parents[1]/'strategic_game_v1_20261021/parents_100_v1/parents.jsonl'


def fixture(players, rounds=3):
    parents = map(json.loads, POOL.read_text().splitlines())
    raw = copy.deepcopy(next(p['raw'] for p in parents if p['configuration']['players']==players))
    raw['game']['round_robin'] = raw['game']['round_robin'][:players]*rounds
    return StrategicRules(raw)


def action(rules, node, name):
    return next(a for a in rules.actions(node) if a.to_dict()['action']==name)


class WindowSemantics(unittest.TestCase):
    def test_proposal_span_two_and_three_players(self):
        for n in (2, 3):
            rules=fixture(n)
            horizon=decision_horizon(rules,rules.initial())
            self.assertEqual(horizon['actual_proposal_turns'], n+1)
            self.assertEqual(horizon['next_own_proposal_index'], n)

    def test_response_stops_after_responder_next_proposal(self):
        rules=fixture(3);root=rules.initial()
        partner=rules.spec.round_robin[1]
        offer=next(a for a in rules.actions(root)
                   if isinstance(a,OfferProposal) and a.offer.partner_id==partner)
        response=rules._apply(root,offer)
        self.assertEqual(decision_horizon(rules,response)['cutoff'],2)
        self.assertEqual(resolve_horizon(rules,response,1)['cutoff'],3)

    def test_late_entry_ends_at_native_terminal(self):
        rules=fixture(3,2);node=rules.initial()
        for _ in range(4):node=rules._apply(node,action(rules,node,'PASS'))
        horizon=decision_horizon(rules,node)
        self.assertIsNone(horizon['next_own_proposal_index'])
        self.assertEqual(horizon['cutoff'],6)
        tree=DecisionWindow(rules,node,rules.worlds,seconds=20)
        self.assertFalse(tree.cutoff_leaves)

    def test_last_offer_response_is_completed_and_only_binding_value_counts(self):
        rules=fixture(2);tree=DecisionWindow(rules,rules.initial(),rules.worlds,seconds=20)
        last_offers=[e for e in tree.entries if e.node.pending is not None
                     and e.node.state.turn_index==tree.cutoff-1]
        self.assertTrue(last_offers)
        self.assertTrue(tree.cutoff_leaves)
        for i,e in enumerate(tree.entries):
            if e.actor is None:
                self.assertIsNone(e.node.pending)
                self.assertEqual(e.node.state.turn_index,tree.cutoff)
                expected=np.array([[np.dot(row,e.node.state.goal_satisfaction())
                                    for row in world] for world in tree.worlds])
                np.testing.assert_allclose(e.payoff,expected)
        for e in last_offers:
            self.assertTrue(all(tree.entries[c].actor is None for c in e.children))

    def test_query_answer_retained_and_other_players_do_not_see_answer(self):
        rules=fixture(2);node=rules.initial();focal=rules.actor(node)
        query=next((a for a in rules.actions(node) if isinstance(a,Investigate)),None)
        if query is None:
            node=rules._apply(node,action(rules,node,'PASS'));focal=rules.actor(node)
            query=next(a for a in rules.actions(node) if isinstance(a,Investigate))
        world=rules.worlds[0];actual=rules.step(node,query,realized_world=world)
        while rules.actor(actual)!=focal:
            actual=rules._apply(actual,action(rules,actual,'PASS'))
        self.assertTrue(rules.observation(actual,focal,world[focal])['private_results'])
        tree=DecisionWindow(rules,node,rules.worlds,seconds=20)
        qi=next(i for a,i in zip(tree.entries[0].actions,tree.entries[0].children) if a==query)
        child=tree.entries[qi]
        self.assertIn((query.player,query.goal),observed_slots(child.node,focal))
        other=child.actor
        for ids in tree.information_groups[qi]:
            expected=[w for w in tree.worlds if w[other]==tree.worlds[ids[0]][other]]
            self.assertEqual(len(ids),len(expected))
        own_next=[(i,e) for i,e in enumerate(tree.entries) if e.actor==focal
                  and e.node.state.turn_index==tree.next_own_proposal_index
                  and (query.player,query.goal) in observed_slots(e.node,focal)]
        self.assertTrue(own_next)
        for i,e in own_next:
            for ids in tree.information_groups[i]:
                self.assertEqual(len({tree.worlds[j][query.player][query.goal] for j in ids}),1)


if __name__=='__main__':unittest.main()
