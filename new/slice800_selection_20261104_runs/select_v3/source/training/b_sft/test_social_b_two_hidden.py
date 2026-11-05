from itertools import product
import unittest

from training.b_sft.social_b_oracle import BeliefOracle, forward_fixture
from training.b_sft.social_b_dataset import random_fixture, question


class TwoHiddenTests(unittest.TestCase):
    def fixture(self):
        raw, prefix = forward_fixture()
        raw['type_catalogues']['1'] = [[x,1,y,0,0] for x,y in product((1,0,-1), repeat=2)]
        return raw, prefix

    def test_joint_filter_does_not_rebuild_marginal_product(self):
        raw, prefix = self.fixture()
        o = BeliefOracle(raw, prefix)
        self.assertEqual(len(o.worlds), 9)
        o.observe({'response':'REJECT'})
        o.observe(dict(action='OFFER', partner_id=2, proposer_action=[0,1], partner_action=[1]))
        support = {(w[1][0],w[1][2]) for w in o.worlds}
        self.assertEqual(len(support), 8)
        self.assertNotIn((1,-1), support)
        for goal in (0,2):
            self.assertEqual(len(o.belief(1,goal)['possible_preferences']), 3)
            self.assertEqual(o.belief(1,goal)['favored'], 'undetermined')
        # Independent marginals would incorrectly restore the excluded pair.
        o.observe({'response':'ACCEPT'})
        self.assertNotIn((1,-1), {(w[1][0],w[1][2]) for w in o.worlds})

    def test_received_offer_is_a_pre_response_checkpoint(self):
        raw, prefix = self.fixture()
        o = BeliefOracle(raw, prefix)
        o.observe({'response':'REJECT'})
        commitments = o.node.state.snapshot_commitments()
        offer = dict(action='OFFER', partner_id=0, proposer_action=[1,0], partner_action=[1])
        o.observe(offer)
        inp = question(o, 1, 0, prefix)
        self.assertEqual(inp['assessment']['phase'], 'response')
        self.assertTrue(inp['assessment']['observer_to_act'])
        self.assertEqual(inp['assessment']['offer_status'], 'awaiting_response_not_binding')
        self.assertEqual(o.node.state.snapshot_commitments(), commitments)
        self.assertEqual(inp['history'][-1], offer)
        self.assertIsNotNone(inp['pending_offer'])

    def test_two_layouts_have_independent_nine_world_priors(self):
        for layout in ('same_partner','different_partners'):
            checked = False
            for seed in range(930000,930020):
                try: raw, prefix, _, _ = random_fixture(seed, hidden=2, layout=layout)
                except ValueError: continue
                o = BeliefOracle(raw, prefix)
                queries = raw['hidden_queries']
                actual = {tuple(w[q['player']][q['goal']] for q in queries) for w in o.worlds}
                self.assertEqual(actual, set(product((1,0,-1), repeat=2)))
                self.assertEqual(queries[0]['player']==queries[1]['player'], layout=='same_partner')
                checked = True
                break
            self.assertTrue(checked)

    def test_two_queries_use_existing_native_b_tool(self):
        from training.b_sft.social_lm_eval import tool_for
        queries = [dict(player=1, goal=0), dict(player=1, goal=2)]
        tool = tool_for('B', dict(queries=queries))['function']
        self.assertEqual(tool['name'], 'SUBMIT_BELIEFS')
        self.assertEqual(tool['parameters']['required'], ['judgments'])
        judgments = tool['parameters']['properties']['judgments']
        self.assertEqual((judgments['minItems'], judgments['maxItems']), (2,2))
        self.assertEqual([v['properties']['goal']['enum'][0] for v in judgments['items']['oneOf']], [0,2])


if __name__ == '__main__': unittest.main()
