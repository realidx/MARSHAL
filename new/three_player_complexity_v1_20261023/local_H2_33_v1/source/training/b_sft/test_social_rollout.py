import json
from copy import deepcopy
from pathlib import Path
import unittest
from training.b_sft.social_rollout import build,queries_for,run_episode,scripted_agent,valid_b
from benac_p.endgame_diagnose import decode_action


class SocialRolloutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw=json.loads((Path(__file__).parent/'fixtures/favored_belief_regression.json').read_text())['fixture']

    def test_full_episode_and_actual_terminal_return(self):
        r=run_episode(self.raw,scripted_agent)
        self.assertEqual(r['status'],'terminal')
        self.assertGreaterEqual(len(r['calls']),4)
        self.assertEqual([c['phase'] for c in r['calls']],['B','P']*(len(r['calls'])//2))
        s,_,_,_=build(self.raw,3000)
        end=s.replay([decode_action(a) for a in r['history']])
        self.assertTrue(end.state.is_terminal)
        self.assertEqual(r['terminal_utility'],s.utility(end))
        self.assertEqual(r['normalized_return'],s.utility(end)/r['utility_scale'])
        self.assertTrue(all(c['input']['queries']==r['queries'] for c in r['calls']))

    def test_query_schedule_covers_multiple_partners(self):
        _,_,types,_=build(self.raw,3000)
        types[2]=(types[2][0],tuple(-v if i==1 else v for i,v in enumerate(types[2][0])))
        self.assertEqual(queries_for(types,0),[dict(player=1,goal=0),dict(player=1,goal=2),dict(player=2,goal=1)])
        # Keep a fixed want outside the newly hidden dimension in every type.
        types[2]=tuple(tuple(1 if i==3 else v for i,v in enumerate(row)) for row in types[2])
        raw=deepcopy(self.raw);raw['type_catalogues']={str(p):[list(r) for r in rs] for p,rs in types.items()}
        r=run_episode(raw,scripted_agent)
        self.assertEqual(r['status'],'terminal')
        self.assertEqual(len(r['queries']),3)

    def test_invalid_public_catalogue_rejected_at_rollout_boundary(self):
        raw=deepcopy(self.raw)
        raw['type_catalogues']['2']=[[-1]*len(raw['own_preferences'])]
        with self.assertRaisesRegex(ValueError,'positive goal'):build(raw,3000)

    def test_prompt_declares_native_rules(self):
        r=run_episode(self.raw,scripted_agent)
        for call in r['calls']:
            self.assertEqual(call['input']['rules']['menu_enabled'],self.raw['game']['menu_enabled'])
            self.assertIn('cannot be unset',call['input']['rules']['commitments'])
            self.assertIn('consume one proposal turn',call['input']['rules']['turns'])

    def test_wrong_model_b_is_passed_to_p_without_repair(self):
        seen=[]
        def agent(phase,payload):
            self.assertNotIn('teacher_counts',json.dumps(payload))
            self.assertNotIn('teacher_sidecar',payload)
            if phase=='B':
                return dict(text='Deliberately wrong diagnostic belief.',answer=[dict(**q,possible_preferences=['avoid'],favored='avoid') for q in payload['queries']])
            seen.append(payload['model_belief'])
            return scripted_agent(phase,payload)
        r=run_episode(self.raw,agent)
        self.assertEqual(r['status'],'terminal')
        self.assertTrue(seen)
        self.assertTrue(all(x['text']=='Deliberately wrong diagnostic belief.' for x in seen))
        self.assertLess(r['teacher_sidecar'][0]['mean_score'],0)

    def test_same_initial_prompt_across_hidden_worlds(self):
        _,node,_,_=build(self.raw,3000)
        first=[]
        def invalid(phase,payload):first.append(payload);return {}
        for w in [node.worlds[0],node.worlds[-1]]:run_episode(self.raw,invalid,world=w)
        self.assertEqual(first[0],first[1])

    def test_invalid_and_truncated_are_not_zero_reward_terminal(self):
        for agent,limit,status in [(lambda phase,payload:{},64,'invalid_B'),(scripted_agent,1,'call_budget')]:
            r=run_episode(self.raw,agent,max_calls=limit)
            self.assertEqual(r['status'],status)
            self.assertIsNone(r['terminal_utility'])
            self.assertIsNone(r['normalized_return'])
        def bad_p(phase,payload):return scripted_agent(phase,payload) if phase=='B' else dict(text='',answer={'action_index':0})
        self.assertEqual(run_episode(self.raw,bad_p)['status'],'invalid_P')

    def test_query_omission_rejected(self):
        self.assertFalse(valid_b(dict(text='',answer=[]),[dict(player=1,goal=0)]))


if __name__=='__main__':unittest.main()
