import unittest
from new.diagnostic_v7.initial_state import InitialEpisode, materialize_start, request
from training.b_sft.social_private_teacher import audit_native
from training.b_sft.prepare_no_catalogue_probe import expand_support, view
from training.b_sft.preference_contract import profile

class InitialTests(unittest.TestCase):
    def raw(self):
        return dict(history=[],ego=0,own_preferences=[1,1],
            type_catalogues={'0':[[1,1]],'1':[[1,1],[1,0],[1,-1]]},
            background_prior=profile('balanced'),
            game=dict(n_players=2,n_actions_per_player=[2,2],max_changes=1,
                      round_robin=[1,0],menu_enabled=False,
                      goals=[dict(goal_id=g,binary=True,required_actions=[dict(player_id=p,action_id=g) for p in (0,1)]) for g in (0,1)]))
    def test_fresh_prior_and_no_history(self):
        raw,public,_=expand_support(self.raw())
        initial={'commitments':[[1,0],[1,0]]}
        ep=InitialEpisode(raw,initial,seconds=15,max_nodes=10000,max_sweeps=128)
        self.assertEqual(ep.tree.entries[0].node.state.transcript,[])
        self.assertEqual(ep.tree.entries[0].node.state.turn_index,0)
        self.assertEqual(ep.tree.entries[0].node.state.public_state()['commitments'],initial['commitments'])
        b=ep.belief(1,1,observer=0,own=[1,1])
        for value in b['preference_weights'].values():self.assertAlmostEqual(value,1/3)
        self.assertTrue(audit_native(ep.tree)['all_values_match'])
        inp=view(ep,public,0,[1,1],[],[],[])
        inp.update(background_prior=profile('balanced'),favored_margin=.1,queries=[dict(player=1,goal=1)])
        task=dict(input=inp,condition='B',task='B',skill='formation')
        text=request(task,initial)['messages'][1]['content']
        self.assertIn('INITIAL STATE AT GAME START',text)
        self.assertNotIn('Preset',text)
        self.assertNotIn('required to do',text)
    def test_conversion_and_rejections(self):
        raw=self.raw()
        r,s=materialize_start(raw,[dict(action='PASS')])
        self.assertEqual(r['game']['round_robin'],[1,0])
        self.assertEqual(s['turn_index'],1)
        self.assertEqual(s['commitments'],[[0,0],[0,0]])
        with self.assertRaises(ValueError):materialize_start(raw,[dict(action='INVESTIGATE',player=0,goal=0)])
        with self.assertRaises(ValueError):materialize_start(raw,[dict(action='OFFER',partner_id=0,proposer_action=[1,0],partner_action=[1,0])])

if __name__=='__main__':unittest.main()
