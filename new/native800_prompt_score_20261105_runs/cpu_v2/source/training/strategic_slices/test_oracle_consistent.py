"""On-policy Bayes entrances and seat/response coverage, without re-solving roots."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
import numpy as np
from .oracle_consistent import oracle_reach,entrance_pool,stratified_entrances,prefix_joint_mass,canonical_parent
from examples.strategic_slices.check_entry_information import restore


class OracleConsistentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        folder=Path(__file__).resolve().parents[2]/'examples/strategic_slices/fixtures'
        f=json.loads((folder/'public_history_information.json').read_text())
        cls.tree=restore(f,f,folder/f['reference_file'])

    def test_goal_renaming_does_not_create_a_new_parent(self):
        from training.strategic_slices.build import sample_parent
        original=sample_parent(2026100609,3,rounds=1)
        renamed=deepcopy(original);order=list(reversed(range(len(original['game']['goals']))))
        renamed['game']['goals']=[deepcopy(original['game']['goals'][g]) for g in order]
        for i,goal in enumerate(renamed['game']['goals']):goal['goal_id']=i
        for p,rows in original['type_catalogues'].items():
            renamed['type_catalogues'][p]=[[row[g] for g in order] for row in rows]
        self.assertEqual(canonical_parent(original),canonical_parent(renamed))
        renamed['background_prior']['weights']['want']+=2
        self.assertNotEqual(canonical_parent(original),canonical_parent(renamed))

    def test_four_proposal_entrance_needs_complete_initial_tree(self):
        from copy import copy
        from training.b_sft.social_private_teacher import PrivateInvestigationRules
        from training.b_sft.preference_contract import profile
        from .bounded import BoundedPrivateWindow
        raw=dict(game=dict(n_players=2,n_actions_per_player=[1,1],round_robin=[0,1,0,1],max_changes=1,
            goals=[dict(goal_id=0,binary=True,required_actions=[dict(player_id=0,action_id=0),dict(player_id=1,action_id=0)])]),
            ego=0,own_preferences=[1],type_catalogues={'0':[[1]],'1':[[1]]},background_prior=profile('balanced'))
        rules=PrivateInvestigationRules(raw)
        full=BoundedPrivateWindow(rules,rules.initial(),rules.worlds,lookahead_rr=2,seconds=20).solve()
        self.assertFalse(any(e['root_index']==0 for e in entrance_pool(full)))
        self.assertTrue(any(e['root_index']==0 and e['remaining_proposals']==4
                            for e in entrance_pool(full,max_remaining_proposals=None)))
        missing=copy(full);missing.certificate=None
        with self.assertRaisesRegex(ValueError,'certified initial terminal'):
            entrance_pool(missing,max_remaining_proposals=4)
        truncated=BoundedPrivateWindow(rules,rules.initial(),rules.worlds,lookahead_rr=1,horizon_mode='rr',seconds=20).solve()
        with self.assertRaisesRegex(ValueError,'certified initial terminal'):
            entrance_pool(truncated,max_remaining_proposals=None)

    def test_all_selected_posteriors_follow_independent_path_likelihood(self):
        tree=self.tree
        for entrance in stratified_entrances(entrance_pool(tree)):
            index,mass=prefix_joint_mass(tree,entrance['history'],entrance['ego'],entrance['entry_world_weights'])
            self.assertEqual(index,entrance['root_index'])
            self.assertAlmostEqual(float(mass.sum()),entrance['oracle_information_set_mass'])

    def test_tree_terminal_probability_is_one(self):
        reach,_=oracle_reach(self.tree)
        total=sum(float(mass.sum()) for i,mass in reach.items() if self.tree.entries[i].actor is None)
        self.assertAlmostEqual(total,1.)

    def test_responses_and_all_players_are_eligible(self):
        pool=entrance_pool(self.tree)
        self.assertEqual({r['ego'] for r in pool},{0,1,2})
        self.assertEqual({r['decision_kind'] for r in pool},{'proposal','response'})
        self.assertTrue(any(r['decision_kind']=='response' and r['focal_next_proposal_offset'] is None for r in pool))

    def test_prior_reset_is_rejected_when_history_is_informative(self):
        tree=self.tree;found=False
        for row in entrance_pool(tree):
            w=np.array(row['entry_world_weights']);ids=np.flatnonzero(w>0)
            prior=np.zeros(tree.w);prior[ids]=tree.world_weights[ids];prior/=prior.sum()
            if not np.allclose(prior,w):
                with self.assertRaisesRegex(ValueError,'Posterior'):
                    prefix_joint_mass(tree,row['history'],row['ego'],prior)
                found=True;break
        self.assertTrue(found)

    def test_oracle_zero_probability_path_is_rejected(self):
        tree=self.tree;reach,histories=oracle_reach(tree)
        for i,mass in reach.items():
            e=tree.entries[i]
            if e.actor is None:continue
            for ai,child in enumerate(e.children):
                target=tree.entries[child]
                if target.actor is not None and float((mass*tree.policy[i][ai]).sum())==0:
                    ids=tree.information_groups[child][0];posterior=np.zeros(tree.w);posterior[ids]=1/len(ids)
                    with self.assertRaisesRegex(ValueError,'zero-probability'):
                        prefix_joint_mass(tree,histories[i]+[ai],target.actor,posterior)
                    return
        self.fail('Native fixture lacks a zero-probability decision branch')

if __name__=='__main__':unittest.main()
