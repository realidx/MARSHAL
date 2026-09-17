"""Regression checks for supervision contracts and task-specific sampling."""
import unittest

from training.b_sft.social_cases_expand import information_fixture
from training.b_sft.social_dataset_v3 import evidence_cohort, expanded_setups, qualification
from training.b_sft.online_social import OnlineSocial


class DatasetV3Tests(unittest.TestCase):
    def test_public_expansions_preserve_round_robin_and_legal_prefix(self):
        raw,_=information_fixture()
        count=0
        for game,prefix,_ in expanded_setups(raw):
            n=game['game']['n_players'];order=game['game']['round_robin']
            for i in range(0,len(order),n):self.assertEqual(sorted(order[i:i+n]),list(range(n)))
            env=OnlineSocial(game,prefix)
            self.assertFalse(env.terminal)
            self.assertEqual(env.actor,game['ego'])
            self.assertEqual(env.worlds,env.game.worlds)  # Public setup is not private evidence.
            count+=1
        self.assertGreaterEqual(count,4)

    def test_b_evidence_survives_easy_terminal_p_and_keeps_no_inference_control(self):
        def row(i,poss,mask=True):
            return dict(id=i,topology='one',supervision=dict(P_basis='direct_terminal'),
                        teacher=dict(B_aux_mask=mask,B_by_target=[dict(answer=dict(
                            possible_preferences=poss,favored=poss[0] if len(poss)==1 else 'undetermined'))]))
        rows=[row('avoid',['avoid']),row('want',['want']),row('full',['want','neutral','avoid']),
              row('native-order',['neutral'],False)]
        chosen=evidence_cohort(rows)
        self.assertEqual({r['id'] for r in chosen},{'avoid','want','full'})

    def test_terminal_p_supervision_does_not_depend_on_fragile_b(self):
        raw,_=information_fixture()
        prefix=[dict(action='PASS') for _ in range(5)]
        prefix.append(dict(action='OFFER',partner_id=0,proposer_action=[1],partner_action=[1,0]))
        env=OnlineSocial(raw,prefix);env.fragile=True
        q=qualification(env,env.p_reference_values())
        self.assertFalse(q['B_aux_mask'])
        self.assertEqual(q['P_basis'],'direct_terminal')
        self.assertTrue(q['P_aux_mask'])


if __name__=='__main__':unittest.main()
