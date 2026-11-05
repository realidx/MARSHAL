from fractions import Fraction
import json
import unittest
from unittest.mock import patch

from training.b_sft.social_terminal_teacher import InvestigationRules,Investigate,TerminalEpisode,TerminalWindow
from training.b_sft.debug.audit_investigation_value import (
    information_value_fixture,exact_root_rows,visibility_effects,no_result_control,
)
from benac_p.endgame_diagnose import decode_action


class InvestigationValueTests(unittest.TestCase):
    def test_value_depends_on_information_reaching_the_pivotal_player(self):
        raw,prefix=information_value_fixture()
        e=TerminalEpisode(raw,prefix)
        rows=exact_root_rows(e)
        self.assertEqual({r['expected_payoffs'][0] for r in rows if r['action'].get('action')!='INVESTIGATE'},{'0'})
        self.assertEqual([r['expected_payoffs'][0] for r in rows if r['action'].get('action')=='INVESTIGATE'],['1/3'])
        effects={r['result_hidden_from']:r['expected_payoffs'][0] for r in visibility_effects(e)}
        self.assertEqual(effects,{0:'1/3',1:'1/3',2:'0'})
        self.assertEqual(no_result_control(e)['expected_payoffs'][0],'0')

    def test_same_preferences_deadline_makes_investigation_strictly_worse(self):
        raw,prefix=information_value_fixture(deadline=True)
        rows=exact_root_rows(TerminalEpisode(raw,prefix))
        self.assertEqual(max(Fraction(r['expected_payoffs'][0]) for r in rows if r['action'].get('action')!='INVESTIGATE'),1)
        self.assertEqual([r['expected_payoffs'][0] for r in rows if r['action'].get('action')=='INVESTIGATE'],['0'])

    def test_choose_relevant_target_over_an_independent_completed_goal(self):
        raw,prefix=information_value_fixture(extra_target=True)
        rows=exact_root_rows(TerminalEpisode(raw,prefix))
        targets={r['action']['goal']:r['expected_payoffs'][0] for r in rows if r['action'].get('action')=='INVESTIGATE'}
        self.assertEqual(targets,{3:'1/3',4:'0'})

    def test_execution_and_outcome_do_not_require_teacher_oracle(self):
        raw,_=information_value_fixture()
        with patch.object(TerminalWindow,'solve',side_effect=AssertionError('Self-play must not call teacher')):
            rules=InvestigationRules(raw)
            world=rules.worlds[1]
            node=rules.initial()
            with self.assertRaisesRegex(ValueError,'private world'):
                rules.step(node,Investigate(1,3))
            node=rules.step(node,Investigate(1,3),realized_world=world)
            public=node.state.public_state()
            self.assertEqual(public['transcript'][-1]['revealed_preference'],'avoid')
            self.assertNotIn('private_preferences',json.dumps(public))
            self.assertEqual(public['investigation_remaining'],0)
            self.assertFalse(any(isinstance(a,Investigate) for a in rules.actions(node)))
            for a in (dict(action='OFFER',partner_id=0,proposer_action=[1],partner_action=[1]),
                      dict(response='ACCEPT'),dict(action='PASS')):
                node=rules.step(node,decode_action(a))
            self.assertEqual(rules.terminal_payoffs(node,world),(1.,1.,-1.))
            # A legal nonteacher action is still valid self-play exploration.
            other=rules.step(rules.initial(),decode_action(dict(action='PASS')))
            self.assertEqual(other.state.turn_index,1)

    def test_target_ids_are_not_coerced_from_bool_or_float(self):
        for p,g in ((True,3),(1,3.0),(-1,0)):
            with self.assertRaises(ValueError):
                Investigate(p,g)


if __name__=='__main__':
    unittest.main()
