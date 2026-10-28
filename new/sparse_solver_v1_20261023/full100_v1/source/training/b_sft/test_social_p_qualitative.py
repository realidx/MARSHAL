from copy import deepcopy
import json
import unittest
import numpy as np

from training.b_sft.social_p_qualitative import terminal_task, confidence_fixture, proposal_fixture, robust_actions, score


class QualitativePlanningTests(unittest.TestCase):
    def test_near_optimal_uses_worst_case_regret_and_preserves_social_ties(self):
        worlds=(((1,),),((-1,),))
        values=np.array([[[1,0],[1,0]],[[.95,0],[.95,0]],[[.95,0],[0,0]]])
        self.assertEqual(robust_actions(values,0,worlds,[],offer_response=True)['acceptable'],[0])
        self.assertEqual(robust_actions(values,0,worlds,[],offer_response=True,own_tolerance=.1)['acceptable'],[0,1])
        # Own-value tolerance must not excuse a bad social choice on a true tie.
        values=np.array([[[1,1],[1,1]],[[1,0],[1,0]]])
        self.assertEqual(robust_actions(values,0,worlds,[],offer_response=True,own_tolerance=.1)['acceptable'],[0])

    def test_learner_tolerance_does_not_change_partner_behavior(self):
        raw,prefix=proposal_fixture()
        claims=[dict(event=[dict(player=1,goal=0,value=1)],level='likely')]
        strict=terminal_task(raw,prefix,claims,allow_proposal=True)
        near=terminal_task(raw,prefix,claims,allow_proposal=True,own_tolerance=.1,social_tolerance=.1)
        self.assertEqual(strict['teacher']['partner_policies'],near['teacher']['partner_policies'])
        self.assertEqual(strict['teacher']['payoffs'],near['teacher']['payoffs'])
        self.assertNotEqual(strict['version'],near['version'])

    def test_small_social_loss_allowed_but_large_loss_and_own_loss_still_rejected(self):
        worlds=(((1,),),((-1,),))
        values=np.array([[[2,1],[2,1]],[[2,.98],[2,.98]],[[2,.5],[2,.5]],[[1.5,10],[1.5,10]]])
        self.assertEqual(robust_actions(values,0,worlds,[],offer_response=True,own_tolerance=.05)['acceptable'],[0])
        result=robust_actions(values,0,worlds,[],offer_response=True,own_tolerance=.05,social_tolerance=.05)
        self.assertEqual(result['acceptable'],[0,1])
        # The entire qualitative belief region must pass, not one favorable world.
        values[1,1,1]=.5
        self.assertEqual(robust_actions(values,0,worlds,[],offer_response=True,own_tolerance=.05,social_tolerance=.05)['acceptable'],[0])

    def task(self,level='likely',variant=0):
        raw,prefix=confidence_fixture()
        return terminal_task(raw,prefix,[dict(event=[dict(player=1,goal=0,value=1)],level=level)],variant=variant)

    def test_weak_and_strong_confidence_require_different_native_actions(self):
        weak=self.task('slightly_likely');strong=self.task('very_likely')
        self.assertEqual(weak['teacher']['acceptable_actions'],[{'response':'REJECT'}])
        self.assertEqual(strong['teacher']['acceptable_actions'],[{'response':'ACCEPT'}])
        # Same physical decision, same support, same own utility; only confidence changes.
        self.assertEqual(weak['input']['pending_offer'],strong['input']['pending_offer'])
        self.assertEqual(weak['teacher']['worlds'],strong['teacher']['worlds'])
        np.testing.assert_equal(np.array(weak['teacher']['payoffs'])[:,:,0],0)

    def test_ambiguous_language_has_no_hidden_point_probability_gold(self):
        for level in ('possible','likely'):
            t=self.task(level)
            self.assertEqual(t['teacher']['certificate']['status'],'ambiguous_information')
            self.assertEqual(t['teacher']['acceptable_actions'],[])
            c=dict(raw_message=dict(tool_calls=[dict(function=dict(name='SUBMIT_ACTION',arguments='{"response":"ACCEPT"}'))]))
            self.assertIsNone(score(t,c)['reward'])

    def test_joint_support_and_paraphrases_preserved_without_numeric_beliefs(self):
        a=self.task('very_likely');b=self.task('very_likely',1)
        self.assertEqual(a['teacher']['acceptable_actions'],b['teacher']['acceptable_actions'])
        self.assertNotEqual(a['request']['messages'],b['request']['messages'])
        self.assertEqual(len(a['input']['supplied_belief']['possible_situations']),2)
        text=json.dumps(a['request'])
        for secret in ('audit_envelopes','payoffs','acceptable_actions','0.75','0.98','history'):
            self.assertNotIn(secret,text)

    def test_impossible_excludes_but_unlikely_retains(self):
        self.assertEqual(len(self.task('impossible')['teacher']['worlds']),1)
        self.assertEqual(len(self.task('unlikely')['teacher']['worlds']),2)
        self.assertEqual(len(self.task('almost_certain')['teacher']['worlds']),2)

    def test_primary_utility_and_social_tie_faces(self):
        worlds=(((1,),),((-1,),))
        # ACCEPT is own-superior only away from p=0; at the tie it harms others.
        payoffs=np.array([[[1,-100],[0,-1]],[[0,0],[0,0]]],dtype=float)
        result=robust_actions(payoffs,0,worlds,[],offer_response=True)
        self.assertEqual(result['status'],'ambiguous_information')
        certain=[dict(event=[dict(player=0,goal=0,value=1)],level='certain')]
        self.assertEqual(robust_actions(payoffs,0,worlds,certain,offer_response=True)['acceptable'],[0])

    def test_native_only_format_failure_and_infrastructure_mask(self):
        t=self.task('very_likely')
        for action,value in ((dict(response='ACCEPT'),1),(dict(response='REJECT'),0)):
            c=dict(raw_message=dict(tool_calls=[dict(function=dict(name='SUBMIT_ACTION',arguments=json.dumps(action)))]))
            self.assertEqual(score(t,c)['reward'],value)
        self.assertEqual(score(t,dict(raw_message=dict(content='SUBMIT_ACTION({})')))['reward'],-1)
        self.assertIsNone(score(t,dict(status='infrastructure_failure'))['reward'])

    def test_nonterminal_cannot_be_silently_scored_as_terminal(self):
        raw,prefix=confidence_fixture();raw['game']['round_robin']*=2
        with self.assertRaisesRegex(ValueError,'Nonterminal'):
            terminal_task(raw,prefix,[])

    def test_proposal_uses_confidence_for_own_risk_not_only_social_ties(self):
        raw,prefix=proposal_fixture()
        tasks=[]
        for level in ('slightly_likely','almost_certain'):
            tasks.append(terminal_task(raw,prefix,[dict(event=[dict(player=1,goal=0,value=1)],level=level)],allow_proposal=True))
        weak,strong=tasks
        self.assertEqual({a['partner_id'] for a in weak['teacher']['acceptable_actions']},{2})
        self.assertEqual({a['partner_id'] for a in strong['teacher']['acceptable_actions']},{1})
        # Direct native payoff: safe agreement earns 3 in both worlds; risky
        # agreement earns 4 iff the unknown partner wants its goal.
        for t,expected in ((weak,[3,3]),(strong,[4,0])):
            action=t['teacher']['acceptable_actions'][0]
            index=t['input']['legal_actions'].index(action)
            self.assertEqual(np.array(t['teacher']['payoffs'])[index,:,0].tolist(),expected)
        self.assertEqual(weak['input']['current_commitments'],strong['input']['current_commitments'])
        self.assertIn('public',weak['input']['supplied_belief']['perspective'])

    def test_partner_extra_ties_cannot_be_hidden_by_one_common_response(self):
        from training.b_sft.social_p_qualitative import proposal_payoffs
        from types import SimpleNamespace
        # The responder is indifferent on own utility. Its social comparison
        # ties at the boundary p=1/2, adding REJECT to an otherwise ACCEPT policy.
        worlds=(((0,),(1,)),((0,),(-1,)))
        class Action:
            def __init__(self,name):self.name=name
            def to_dict(self):return {'response':self.name}
        offer=Action('offer');accept=Action('ACCEPT');reject=Action('REJECT')
        root=SimpleNamespace(stage=0)
        child=SimpleNamespace(stage=1,pending=True,state=SimpleNamespace(is_terminal=False))
        ends={accept:SimpleNamespace(state=SimpleNamespace(is_terminal=True,goal_satisfaction=lambda:np.array([1]))),
              reject:SimpleNamespace(state=SimpleNamespace(is_terminal=True,goal_satisfaction=lambda:np.array([0])))}
        rules=SimpleNamespace(actions=lambda n:[offer] if n is root else [accept,reject],
            _apply=lambda n,a:child if n is root else ends[a],actor=lambda n:0)
        claims=[dict(event=[dict(player=1,goal=0,value=1)],level='likely')]
        with self.assertRaisesRegex(ValueError,'tie set changes'):
            proposal_payoffs(rules,root,worlds,claims)


if __name__=='__main__':unittest.main()
