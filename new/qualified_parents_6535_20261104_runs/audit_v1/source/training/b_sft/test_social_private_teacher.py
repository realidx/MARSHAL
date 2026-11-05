from copy import deepcopy
import unittest

import numpy as np

from training.b_sft.social_bp_curriculum import result_use_fixture, acceptable
from training.b_sft.social_bp_curriculum_eval import request, score
from training.b_sft.debug.audit_private_teaching import make_p
from training.b_sft.social_private_teacher import (
    PrivateInvestigationRules, PrivateEpisode, Investigate, audit_native,
)
from benac_p.endgame_diagnose import decode_action


def result_episode():
    raw, prefix = result_use_fixture('want')
    prefix[3].pop('revealed_preference')
    return raw, prefix


class PrivateTeacherTests(unittest.TestCase):
    def test_environment_private_truth_and_individual_quota(self):
        raw, _ = result_episode()
        rules = PrivateInvestigationRules(raw)
        root = rules.initial()  # P2 acts first.
        children = [rules.step(root, Investigate(1, 0), realized_world=w) for w in rules.worlds]
        self.assertEqual(children[0].state.public_state(), children[1].state.public_state())
        self.assertEqual(children[0].worlds, root.worlds)
        for w, child in zip(rules.worlds, children):
            obs = rules.observation(child, 2, w[2])
            self.assertEqual(obs['private_results'][0]['preference'], 'want' if w[1][0] == 1 else 'avoid')
            self.assertEqual(rules.observation(child, 0, w[0])['private_results'], [])
            self.assertNotIn('revealed_preference', str(child.state.public_state()))
            self.assertEqual(child.state.public_state()['investigation_remaining_by_player'], [1,1,0])
            self.assertEqual(child.state.turn_index,1)
            self.assertEqual(child.state.snapshot_commitments(),root.state.snapshot_commitments())
        # Querying a publicly known preference is legal, but consumes P1's quota.
        child = rules.step(children[0], Investigate(0, 0), realized_world=rules.worlds[0])
        self.assertEqual(child.state.public_state()['investigation_remaining_by_player'], [1,0,0])
        self.assertIn(Investigate(1,0),rules.actions(child))  # P0 may query same target.
        child = rules._apply(child,decode_action({'action':'PASS'}))
        self.assertFalse(any(isinstance(a,Investigate) for a in rules.actions(child)))
        self.assertEqual(root.state.private_results,((),(),()))
        with self.assertRaises(ValueError):rules.step(root,Investigate(2,0),realized_world=rules.worlds[0])
        with self.assertRaises(ValueError):rules.step(root,Investigate(1,0))

    def test_private_result_changes_own_action_without_public_belief_leak(self):
        raw,prefix=result_episode()
        e=PrivateEpisode(raw,prefix)
        self.assertEqual(len(e.tree.worlds),2)
        self.assertTrue(audit_native(e.tree)['all_values_match'])
        for value,action in ((1,[1,0]),(-1,[0,1])):
            row=e.choices(raw['own_preferences'],[(1,0,value)])
            expected=dict(action='OFFER',partner_id=1,proposer_action=action,partner_action=[1])
            self.assertEqual(row['admissible_actions'],[expected])
            self.assertEqual([row['actions'][i] for i in acceptable(row['values'],0)],[expected])
            belief=e.belief(1,0,observer=0,own=raw['own_preferences'],private_results=[(1,0,value)])
            self.assertEqual(belief['possible_preferences'],['want' if value==1 else 'avoid'])
        outsider=e.belief(1,0,observer=2,own=raw['type_catalogues']['2'][0])
        self.assertEqual(outsider['possible_preferences'],['want','avoid'])
        self.assertEqual(outsider['favored'],'undetermined')
        with self.assertRaises(ValueError):e.choices(raw['own_preferences'])
        # Later public behavior can transmit evidence despite the private answer.
        e.observe(dict(action='OFFER',partner_id=1,proposer_action=[1,0],partner_action=[1]))
        self.assertEqual(e.belief(1,0,observer=2,own=raw['type_catalogues']['2'][0])['favored'],'want')

    def test_last_turn_query_cost_and_no_world_conditioned_omniscience(self):
        raw,prefix=result_episode()
        prefix[3]={'action':'PASS'}
        e=PrivateEpisode(raw,prefix)
        row=e.choices(raw['own_preferences'])
        self.assertEqual(max(v[0] for v in row['values']),1)
        self.assertTrue(all(v[0]==0 for a,v in zip(row['actions'],row['values']) if a.get('action')=='INVESTIGATE'))
        # Same own type and no received result => same action distribution.
        np.testing.assert_array_equal(e.tree.policy[0][:,0],e.tree.policy[0][:,1])
        self.assertGreater(e.tree.certificate['information_set_checks'],0)
        self.assertEqual(e.tree.certificate['game_version'],'social-private-investigate-per-player-v1')

    def test_full_information_agrees_with_native_backward_induction(self):
        raw,prefix=result_episode()
        raw['type_catalogues']['1']=[raw['type_catalogues']['1'][0]]
        prefix[3]={'action':'PASS'}
        e=PrivateEpisode(raw,prefix)
        values=[None]*len(e.tree.entries)
        for i in reversed(range(len(values))):
            node=e.tree.entries[i]
            if node.actor is None:
                values[i]=node.payoff[0]
                continue
            av=np.array([values[c] for c in node.children])
            own=av[:,node.actor]
            social=av.sum(axis=1)-own
            first=np.flatnonzero(own==own.max())
            final=first[social[first]==social[first].max()]
            values[i]=av[final].mean(axis=0)
            np.testing.assert_allclose(values[i],e.tree.values[i][0])
        again=PrivateEpisode(raw,prefix)
        self.assertEqual(e.tree.certificate['policy_sha256'],again.tree.certificate['policy_sha256'])

    def test_private_request_has_correct_rules_without_teacher_answers(self):
        raw,prefix=result_episode()
        e=PrivateEpisode(raw,prefix)
        task=make_p(e,[(1,0,1)],'result_use')
        task['teacher']['sentinel']='PRIVATE_TEACHER_SECRET'
        payload=request(task)
        text=str(payload)
        self.assertIn('Each player has one use per game',text)
        self.assertIn('only the investigator receives',text)
        self.assertNotIn('single shared',text)
        self.assertNotIn('PRIVATE_TEACHER_SECRET',text)
        self.assertNotIn('action_values',text)
        self.assertNotIn('preference_weights',text)


if __name__=='__main__':unittest.main()
