import unittest
import tempfile
import json
from pathlib import Path
from training.b_sft.coverage_batch import make_game,select,read_complete,validate_catalogues
from training.b_sft.social_rollout import build,queries_for
from training.b_sft.random_funnel import screen


class CoverageBatchTests(unittest.TestCase):
    def test_multiple_partners_replay_and_fixed_queries(self):
        raw,world=make_game(98000,3,1,4,'multi_partner')
        s,node,types,_=build(raw,1000)
        self.assertIn(world,node.worlds)
        self.assertEqual(len({q['player'] for q in queries_for(types,s.ego)}),2)
        self.assertEqual(len(node.worlds),9)
        r=screen(raw,1000,2)
        self.assertEqual(r['joint_worlds'],9)
        self.assertEqual(len(r['B']),2)

    def test_partial_timeout_record_is_not_completed(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'records.jsonl';p.write_text('{"ok":1}\n{"partial":')
            self.assertEqual(read_complete(p),[{'ok':1}])
            p.write_text('{"ok":1}\nBROKEN\n')
            with self.assertRaises(json.JSONDecodeError):read_complete(p)

    def test_joint_catalogue_cannot_admit_all_neutral_goal(self):
        raw,_=make_game(98000,3,1,4,'multi_partner')
        raw['type_catalogues']={'0':[[0,1,0,0]],'1':[[0,0,1,0]],'2':[[0,0,0,1]]}
        raw['own_preferences']=raw['type_catalogues'][str(raw['ego'])][0][:]
        with self.assertRaisesRegex(ValueError,'all-neutral'):
            validate_catalogues(raw)

    def test_hidden_mode_keeps_same_physical_game(self):
        a,_=make_game(98000,3,1,4,'single')
        b,_=make_game(98000,3,1,4,'multi_goal')
        self.assertEqual(a['game'],b['game'])
        self.assertEqual(len(a['hidden_dimensions']),1)
        self.assertEqual(len(b['hidden_dimensions']),2)

    def test_selection_groups_modes_and_excludes_failures(self):
        records=[]
        for mode in ['single','multi_goal','multi_partner']:
            f,_=make_game(98000,3,1,4,mode)
            records.append(dict(fixture=f,mode=mode,screen=dict(status='ordinary_control',categories=[])))
        choices=select(records,8)
        self.assertEqual(len(choices),1)
        self.assertEqual(len(choices[0]['records']),3)
        self.assertIn('multi_partner',choices[0]['features'])
        self.assertEqual(select([dict(records[0],screen=dict(status='unavailable',categories=['fake']))]),[])


if __name__=='__main__':unittest.main()
