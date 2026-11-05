import unittest

import numpy as np

from benac_p.schema import OfferProposal
from training.b_sft.preference_contract import world_weights
from training.b_sft.social_terminal_teacher import Investigate
from training.strategic_slices.bounded import BoundedPrivateWindow
from new.game_design_feasibility_20261021.design import BudgetRules, generate, count_public_tree


class DesignChecks(unittest.TestCase):
    def raw(self):
        return generate(2026102101,players=2,actions=[2,1],goals=2,rounds=3,hidden=2)

    def test_two_queries_preserve_private_answers_and_turn_cost(self):
        rules=BudgetRules(self.raw(),2,1)
        node=rules.initial(); actor=rules.actor(node); world=rules.worlds[-1]
        for step in range(3):
            a=next(a for a in rules.actions(node) if isinstance(a,Investigate))
            node=rules.step(node,a,realized_world=world)
        self.assertEqual(node.state.turn_index,3)
        self.assertEqual(node.state.query_used[actor],2)
        self.assertEqual(len(node.state.private_results[actor]),2)
        self.assertFalse(any(isinstance(a,Investigate) for a in
            rules.actions(NodeForActor(rules,node,actor))))
        other=1-actor
        self.assertEqual(len(node.state.private_results[other]),1)
        self.assertEqual(len(rules.observation(node,other,world[other])['private_results']),1)

    def test_offer_is_charged_before_response_and_never_refunded(self):
        rules=BudgetRules(self.raw(),1,1); root=rules.initial(); actor=rules.actor(root)
        offer=next(a for a in rules.actions(root) if isinstance(a,OfferProposal))
        pending=rules.step(root,offer)
        self.assertEqual(pending.state.offer_used[actor],1)
        self.assertEqual(root.state.offer_used[actor],0)
        self.assertEqual(pending.state.turn_index,0)
        for response in rules.actions(pending):
            child=rules.step(pending,response)
            self.assertEqual(child.state.offer_used[actor],1)
            self.assertEqual(child.state.turn_index,1)

    def test_counts_match_independent_full_tree_and_prior_support(self):
        raw=generate(5,players=2,actions=[1,1],goals=1,rounds=2,hidden=2)
        rules=BudgetRules(raw,1,1)
        counts=count_public_tree(rules)
        tree=BoundedPrivateWindow(rules,rules.initial(),rules.worlds,
            world_weights=world_weights(rules.worlds,raw['background_prior']),
            lookahead_rr=10,max_nodes=20000,seconds=20)
        self.assertEqual(counts['public_histories'],len(tree.entries))
        self.assertEqual(counts['terminal_histories'],sum(e.actor is None for e in tree.entries))
        self.assertFalse(tree.cutoff_leaves)
        self.assertEqual(tree.w,9)
        np.testing.assert_allclose(tree.world_weights,np.full(9,1/9))

    def test_hidden_only_menu_count_and_private_knowledge(self):
        raw=generate(7,players=2,actions=[1,1],goals=1,rounds=2,hidden=1)
        rules=BudgetRules(raw,2,1,query_targets='hidden-unobserved')
        tree=BoundedPrivateWindow(rules,rules.initial(),rules.worlds,
            world_weights=world_weights(rules.worlds,raw['background_prior']),
            lookahead_rr=10,max_nodes=20000,seconds=20)
        self.assertEqual(count_public_tree(rules)['public_histories'],len(tree.entries))
        for entry in tree.entries:
            if entry.actor is None:
                continue
            prior=[(ev.player,ev.goal) for ev in entry.node.state.transcript
                   if hasattr(ev,'goal') and ev.proposer_id==entry.actor]
            for action in entry.actions:
                if isinstance(action,Investigate):
                    self.assertNotIn((action.player,action.goal),prior)
                    self.assertGreater(len({r[action.goal] for r in rules.catalogues[action.player]}),1)


def NodeForActor(rules,node,actor):
    # Move the other player's opportunity with PASS to the actor's next proposal.
    while rules.actor(node) != actor:
        a=next(a for a in rules.actions(node) if a.to_dict().get('action')=='PASS')
        node=rules.step(node,a)
    return node


if __name__=='__main__':
    unittest.main()
