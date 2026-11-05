from copy import deepcopy
from pathlib import Path
import json
import tempfile
import unittest

from training.b_sft.dataset_review import family_id,evidence_use,timeline,conservative_b_masks
from training.b_sft.social_rollout import build,queries_for
from training.b_sft.random_funnel import screen
from training.b_sft.assemble_dataset import assemble


class ReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.w=json.loads((Path(__file__).parent/'fixtures/evidence_switch_regression.json').read_text())

    def test_evidence_use_requires_matching_physical_state(self):
        rows=[dict(terminal=False,weight=.5,physical_key='same',actions=['a','b'],q=[2.,0.]),
              dict(terminal=False,weight=.5,physical_key='same',actions=['a','b'],q=[0.,2.])]
        self.assertEqual(evidence_use(rows)['gain'],1.)
        rows[1]['physical_key']='different'
        self.assertEqual(evidence_use(rows)['gain'],0.)
        rows[1]['physical_key']='same';rows[1]['q']=[2.,2.]
        self.assertEqual(evidence_use(rows)['gain'],0.)

    def test_public_evidence_tie_diagnostic_and_ego_interventions(self):
        raw=dict(self.w['fixture'],history=self.w['left']['history'])
        events=timeline(raw);s,_,types,_=build(raw,3000)
        self.assertTrue(events[0]['ego_intervention'])
        self.assertEqual(events[0]['worlds_before'],events[0]['worlds_after'])
        self.assertGreater(events[1]['tie_sensitivity']['excluded_only_by_tie_worlds'],0)
        masks=conservative_b_masks(events,queries_for(types,s.ego))
        self.assertFalse(masks[0]['set_mask'])
        clean=timeline(dict(raw,history=self.w['right']['history']))
        self.assertTrue(conservative_b_masks(clean,queries_for(types,s.ego))[0]['set_mask'])

    def test_family_covers_player_goal_action_renaming(self):
        raw=deepcopy(self.w['fixture']);g=raw['game']
        # Add a second commitment per player for nontrivial action permutation.
        g['n_actions_per_player']=[2]*3
        g['forbidden_actions']=[[0,1],[0,0],[1,0]]
        clone=deepcopy(raw);cg=clone['game'];mapping={0:2,1:0,2:1}
        cg['round_robin']=[mapping[p] for p in g['round_robin']]
        cg['forbidden_actions']=[None]*3
        for p in range(3):cg['forbidden_actions'][mapping[p]]=list(reversed(g['forbidden_actions'][p]))
        cg['goals']=list(reversed(cg['goals']))
        for i,goal in enumerate(cg['goals']):
            goal['goal_id']=i
            for a in goal['required_actions']:a['player_id']=mapping[a['player_id']];a['action_id']=1-a['action_id']
        self.assertEqual(family_id(raw),family_id(clone))
        cg['max_changes']+=1
        self.assertNotEqual(family_id(raw),family_id(clone))

    def test_family_guard_applies_before_assembly(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);raw=self.w['fixture'];clone=deepcopy(raw)
            clone['game']['goals']=list(reversed(clone['game']['goals']))
            for i,g in enumerate(clone['game']['goals']):g['goal_id']=i
            for name,r,split in [('train',raw,'train'),('test',clone,'test')]:
                (p/(name+'.json')).write_text(json.dumps(dict(fixtures=[r],split=split)))
            with self.assertRaisesRegex(ValueError,'Isomorphic family crosses'):
                assemble([],[],p/'out',fixture_packs=[p/'train.json',p/'test.json'])

    def test_flat_q_is_control_not_information_planning_certificate(self):
        raw=json.loads((Path(__file__).parent/'fixtures/action_invariant_review.json').read_text())
        r=screen(raw,max_arms=8)
        self.assertEqual(r['status'],'verified')
        self.assertEqual(r['root_q_range'],0)
        self.assertFalse(r['p_auxiliary_mask'])
        self.assertIn('P_action_invariant_control',r['categories'])
        self.assertNotIn('informative_action_tied_or_best',r['categories'])


if __name__=='__main__':unittest.main()
