import json
from pathlib import Path
import unittest
from training.b_sft.random_funnel import screen
from benac_p.endgame_mine import candidates


class RandomFunnelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.w=json.loads((Path(__file__).parent/'fixtures/evidence_switch_regression.json').read_text())

    def test_failed_search_is_not_negative_sample(self):
        r=screen(self.w['fixture'],max_nodes=1)
        self.assertEqual(r['status'],'unavailable')
        self.assertIn(r['stage'],['replay','evidence_screen','terminal_value_verification'])

    def test_ordinary_control_is_retained_not_strict_rejected(self):
        raw=dict(self.w['fixture'],history=self.w['left']['history'])
        r=screen(raw)
        self.assertEqual(r['status'],'ordinary_control')
        self.assertEqual(r['joint_worlds'],1)

    def test_sampled_arms_never_claim_exhaustiveness(self):
        r=screen(self.w['fixture'],max_arms=1)
        self.assertNotEqual(r['status'],'unavailable')
        self.assertEqual(r['sampled_arms'],1)
        self.assertFalse(r['all_arms_examined'])
        self.assertFalse(r.get('positive_net_information_value_proven',False))

    def test_path_seed_does_not_change_game_or_default_behavior(self):
        def sample(path_seed):
            events=[]
            rows=list(candidates(97000,max_nodes=1000,actions_per_player=1,n_goals=4,
                max_query_sets=1,trajectory_seed=path_seed,on_event=events.append))
            return rows,events
        a,ea=sample(None);b,eb=sample(97000);c,ec=sample(97001)
        self.assertEqual(a,b)
        self.assertEqual(ea[0]['game'],ec[0]['game'])
        self.assertTrue(any(e['event'] in ('trajectory_finished','trajectory_failed','configuration_skipped') for e in eb))
        self.assertEqual({tuple(e['goals']) for e in ea if e['event']=='configuration_started'},
                         {tuple(e['goals']) for e in ec if e['event']=='configuration_started'})


if __name__=='__main__':unittest.main()
