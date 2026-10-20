"""Semantic regression checks for the isolated rule change."""
import unittest

from new.offer_budget_mechanism_20261021.research import (
    OfferQuotaRules, small_parents, one_round_control,
)
from training.b_sft.social_private_teacher import PrivateInvestigationRules
from training.b_sft.social_terminal_teacher import Investigate
from benac_p.schema import OfferProposal, PassProposal


class QuotaSemantics(unittest.TestCase):
    def setUp(self):
        self.raw = next(small_parents())[1]
        self.rules = OfferQuotaRules(self.raw, 1)
        self.root = self.rules.initial()

    def test_charge_precedes_response_and_is_not_refunded(self):
        offer = next(a for a in self.rules.actions(self.root) if isinstance(a, OfferProposal))
        pending = self.rules._apply(self.root, offer)
        self.assertEqual(pending.state.offer_used, (1, 0))
        self.assertEqual(pending.state.turn_index, 0)
        self.assertEqual(self.root.state.offer_used, (0, 0))
        for response in self.rules.actions(pending):
            child = self.rules._apply(pending, response)
            self.assertEqual(child.state.offer_used, (1, 0))
            self.assertEqual(child.state.turn_index, 1)
            # Advance P1 without using P1's independent quota.
            child = self.rules._apply(child, PassProposal())
            self.assertFalse(any(isinstance(a, OfferProposal) for a in self.rules.actions(child)))
            self.assertTrue(any(isinstance(a, Investigate) for a in self.rules.actions(child)))
            self.assertIn(PassProposal(), self.rules.actions(child))
            bypass = next(a for a in self.rules.base.actions(child) if isinstance(a, OfferProposal))
            with self.assertRaises(ValueError):
                self.rules._apply(child, bypass)

    def test_actual_private_delivery_and_turn_cost_unchanged(self):
        base = PrivateInvestigationRules(self.raw)
        query = Investigate(1, 0)
        world = self.rules.worlds[0]
        modified = self.rules.step(self.root, query, realized_world=world)
        original = base.step(base.initial(), query, realized_world=world)
        self.assertEqual(modified.state.turn_index, original.state.turn_index)
        self.assertEqual(modified.state.investigation_used, original.state.investigation_used)
        self.assertEqual(modified.state.private_results, original.state.private_results)
        self.assertEqual(modified.state.offer_used, (0, 0))
        self.assertEqual(modified.state.private_results[1], ())
        self.assertEqual(self.root.state.private_results, ((), ()))
        self.assertEqual(modified.state.snapshot_commitments(), original.state.snapshot_commitments())

    def test_one_round_limit_is_redundant(self):
        self.assertTrue(one_round_control(self.raw)['verified'])

    def test_invalid_budget_and_independent_reset(self):
        for value in (-1, True, 1.5):
            with self.assertRaises(ValueError):
                OfferQuotaRules(self.raw, value)
        self.assertEqual(self.rules.initial().state.offer_used, (0, 0))
        empty = OfferQuotaRules(self.raw, 0)
        self.assertFalse(any(isinstance(a, OfferProposal) for a in empty.actions(empty.initial())))


if __name__ == '__main__':
    unittest.main()
