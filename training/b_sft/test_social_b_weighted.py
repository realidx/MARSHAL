"""Behavioral checks for cumulative evidence, private information and labels."""
from copy import deepcopy
import json
import random
import unittest

import numpy as np

from training.b_sft.social_b_oracle import BeliefOracle, forward_fixture, VERSION
from training.b_sft.social_b_random_window import RandomTieWindow
from training.b_sft.social_b_dataset import random_fixture, observer_belief, transition, belief_changes, mine
from training.b_sft.shared_teacher import SearchLimit


class WeightedBeliefTests(unittest.TestCase):
    def binary_fixture(self):
        raw, prefix = forward_fixture()
        raw['type_catalogues']['1'] = [raw['type_catalogues']['1'][i] for i in (0, 2)]
        return raw, prefix

    def test_action_likelihood_favors_a_still_uncertain_preference(self):
        raw, prefix = self.binary_fixture()
        o = BeliefOracle(raw, prefix)
        self.assertEqual(o.belief(1, 2)['favored'], 'undetermined')
        o.observe({'response': 'REJECT'})
        # Independently known final tie sets: want always rejects; avoid has
        # equally good ACCEPT/REJECT after BOTH value comparisons.
        self.assertEqual([r['observed_action_likelihood'] for r in o.events[-1]['comparisons']], [1, .5])
        np.testing.assert_allclose(o.weights, [2/3, 1/3])
        b = o.belief(1, 2)
        self.assertEqual(b['possible_preferences'], ['want', 'avoid'])
        self.assertEqual(b['favored'], 'want')
        # Merely sampling execution reveals no seed/evidence to the oracle.
        saved = (o.weights, deepcopy(o.events))
        for seed in range(5): o.sample_action(o.worlds[0][1], random.Random(seed))
        self.assertEqual((o.weights, o.events), saved)

    def test_replanning_and_actual_history_keep_cumulative_weights(self):
        raw, prefix = forward_fixture(rounds=2)
        o = BeliefOracle(raw, prefix)
        world = o.worlds[0]
        products = {w: 1/len(o.worlds) for w in o.worlds}
        while not o.node.state.is_terminal:
            actor = o.rules.actor(o.node)
            np.testing.assert_allclose(o.solve().world_weights, o.weights)
            action = o.sample_action(world[actor], random.Random(len(o.history)))
            o.observe(action)
            event = o.events[-1]
            likelihoods = {tuple(r['own_type']): r['observed_action_likelihood'] for r in event['comparisons']}
            products = {w: mass * likelihoods[w[actor]] for w,mass in products.items() if likelihoods[w[actor]] > 0}
            total = sum(products.values())
            np.testing.assert_allclose(o.weights, [products[w]/total for w in o.worlds])
            self.assertIn(world, o.worlds)
        replay = BeliefOracle.replay(raw, o.events)
        self.assertEqual(replay.events, o.events)
        self.assertEqual(replay.weights, o.weights)

    def test_weighted_root_values_and_certificate(self):
        raw, prefix = self.binary_fixture()
        o = BeliefOracle(raw, prefix)
        o.observe({'response': 'REJECT'})
        o.observe(dict(action='OFFER', partner_id=2, proposer_action=[0, 1], partner_action=[1]), kind='intervention')
        tree = o.solve()
        row = o.choices(o.worlds[0][2])
        for child, value in zip(tree.entries[0].children, row['values']):
            expected = (2*tree.values[child][0] + tree.values[child][1])/3
            self.assertAlmostEqual(value['own'], expected[2])
            self.assertAlmostEqual(value['others'], expected.sum()-expected[2])
        np.testing.assert_allclose(tree.certificate['root_world_weights'], [2/3, 1/3])
        self.assertTrue(tree.certificate['verified'])

    def test_weights_can_change_a_native_action_through_the_social_tie_rule(self):
        # A final offer satisfies G0 and G1 together. P0 gets +1-1=0,
        # while the others get (hidden preference +1)-1. Thus the second
        # comparison must use the belief, even though P0's own values tie.
        requirements=[[(0,0),(1,0)],[(0,0),(1,0),(2,0)],[(0,1),(2,0)]]
        raw=dict(ego=0,own_preferences=[1,-1,0],history=[],
            type_catalogues={'0':[[1,-1,0]],'1':[[v,1,0] for v in (1,0,-1)],'2':[[-1,0,1]]},
            game=dict(n_players=3,n_actions_per_player=[2,1,1],round_robin=[2,0,1],
                max_changes=1,menu_enabled=False,goals=[dict(goal_id=i,binary=True,
                    required_actions=[dict(player_id=p,action_id=a) for p,a in req])
                    for i,req in enumerate(requirements)]))
        prefix=[dict(action='OFFER',partner_id=0,proposer_action=[1],partner_action=[0,0]),
                dict(response='ACCEPT'),dict(action='PASS'),
                dict(action='OFFER',partner_id=0,proposer_action=[1],partner_action=[1,0])]
        uniform=BeliefOracle(raw,prefix)
        self.assertEqual(len(uniform.choices(raw['own_preferences'])['admissible_actions']),2)
        weighted=BeliefOracle(raw,prefix)
        # Deliberately supplied alternate information for a teacher unit check,
        # not a claim that the setup prefix itself generated this posterior.
        weighted.weights=(.4,.4,.2)
        decision=weighted.choices(raw['own_preferences'])
        self.assertEqual(decision['admissible_actions'],[{'response':'ACCEPT'}])
        self.assertEqual([v['own'] for v in decision['values']],[0,0])
        self.assertAlmostEqual(next(v['others'] for v in decision['values'] if v['action']=={'response':'ACCEPT'}),.2)

    def test_intervention_and_failures_do_not_change_weights(self):
        raw, prefix = self.binary_fixture(); o = BeliefOracle(raw, prefix)
        o.observe({'response':'REJECT'})
        saved = o.weights
        o.observe(dict(action='OFFER',partner_id=2,proposer_action=[0,1],partner_action=[1]),kind='intervention')
        self.assertEqual(o.weights, saved)
        before = (o.worlds, o.weights, deepcopy(o.events), deepcopy(o.history))
        o._tree = None; o.max_nodes = 1
        with self.assertRaises(SearchLimit): o.observe({'response':'ACCEPT'})
        self.assertEqual((o.worlds,o.weights,o.events,o.history), before)
        with self.assertRaises(ValueError): o.observe({'response':'ACCEPT','extra':1})
        self.assertEqual((o.worlds,o.weights,o.events,o.history), before)

    def test_observer_private_row_is_not_revealed_to_other_actors(self):
        raw, prefix = forward_fixture()
        raw['type_catalogues']['0'] = [raw['own_preferences'], [1,0,-1,0,0]]
        a = BeliefOracle(raw,prefix)
        other = deepcopy(raw); other['own_preferences'] = raw['type_catalogues']['0'][1]
        b = BeliefOracle(other,prefix)
        self.assertEqual(len(a.worlds),6)
        for own in raw['type_catalogues']['1']:
            self.assertEqual(a.choices(own),b.choices(own))
        a.observe({'response':'REJECT'}); b.observe({'response':'REJECT'})
        self.assertEqual(a.events,b.events)
        self.assertEqual(a.weights,b.weights)
        self.assertEqual(a.belief(0,2)['possible_preferences'], ['want','avoid'])
        self.assertEqual(observer_belief(a,0,2)['possible_preferences'], ['want'])
        self.assertEqual(observer_belief(b,0,2)['possible_preferences'], ['avoid'])

    def test_favored_and_strength_updates_are_not_false_maintenance(self):
        def belief(weights):
            leaders = [k for k,v in weights.items() if v==max(weights.values())]
            return dict(possible_preferences=[k for k,v in weights.items() if v>0],
                        favored=leaders[0] if len(leaders)==1 else 'undetermined',preference_weights=weights)
        a=belief(dict(want=.5,neutral=.5,avoid=0))
        b=belief(dict(want=.7,neutral=.3,avoid=0))
        c=belief(dict(want=.8,neutral=.2,avoid=0))
        d=belief(dict(want=.3,neutral=.7,avoid=0))
        self.assertEqual(transition(a,b),'update')
        self.assertEqual(transition(b,c),'strength_change')
        self.assertEqual(transition(c,d),'update')
        self.assertEqual(transition(d,a),'update')
        self.assertFalse(belief_changes(b,d)['support_changed'])
        self.assertTrue(belief_changes(b,d)['favored_changed'])

    def test_generation_covers_all_hidden_layouts_including_observer(self):
        layouts=set(); players=set(); roles=set(); commitments=set(); goals=set()
        for seed in range(940000,940100):
            try: raw,prefix,_,_=random_fixture(seed)
            except ValueError: continue
            meta=raw['generation'];layouts.add((meta['hidden'],meta['layout']))
            players.add(meta['players']);roles.add(meta['observer_hidden'])
            commitments.add(meta['setup_commitments']);goals.add(meta['goals'])
            self.assertIn(raw['own_preferences'],raw['type_catalogues'][str(raw['ego'])])
        self.assertEqual(layouts,{(1,'same_partner'),(2,'same_partner'),(2,'different_partners')})
        self.assertEqual(players,{3,4});self.assertEqual(roles,{False,True})
        self.assertGreater(len(commitments),1);self.assertGreater(len(goals),1)

    def test_favored_reward_and_temporal_evaluation_use_new_semantics(self):
        from training.b_sft.test_social_b_evaluation import task,completion
        from training.b_sft.social_b_evaluation import request,score_attempt,score_transition,require_current_tasks
        from training.b_sft.social_b_rl import reward
        a=task('a',[],['want','neutral']);b=task('b',[{'action':'PASS'}],['want','neutral'])
        b['gold']['judgments'][0]['favored']='want'
        c=completion(['want','neutral'])
        args=json.loads(c['message']['tool_calls'][0]['function']['arguments']);args['judgments'][0]['favored']='want'
        c['message']['tool_calls'][0]['function']['arguments']=json.dumps(args)
        self.assertEqual(reward(b,c)['reward'],1)
        self.assertEqual(reward(b,completion(['want','neutral']))['reward'],0)
        old=completion(['want','neutral'])
        change=score_transition(a,b,score_attempt(a,old),score_attempt(b,old),dict(player=1,goal=0))
        self.assertTrue(change['missed_update']);self.assertFalse(change['expected_set_change'])
        self.assertTrue(change['expected_favored_change'])
        self.assertNotIn('sole member only',request(b)['messages'][0]['content'])
        require_current_tasks([b])
        b['input']['partner_model']['version']='social-b-bounded-oracle-v3'
        with self.assertRaises(ValueError):require_current_tasks([b])
        self.assertIn('sole member only',request(b)['messages'][0]['content'])


if __name__=='__main__': unittest.main()
