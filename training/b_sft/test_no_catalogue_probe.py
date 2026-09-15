import unittest

from training.b_sft.debug.audit_minimal_teaching import fixture, offer
from training.b_sft.prepare_no_catalogue_probe import expand_support, tasks_from_case, extra_favored_cases, joint_unknown_cases
from training.b_sft.social_bp_curriculum_eval import request


class NoCatalogueProbeTests(unittest.TestCase):
    def test_arbitrary_two_type_support_expands_to_generator_five(self):
        raw=fixture(types=((1,-1),(-1,1)))
        expanded,public,audit=expand_support(raw)
        self.assertEqual(audit['old_worlds'],2)
        self.assertEqual(audit['new_worlds'],5)
        self.assertEqual({tuple(r) for r in expanded['type_catalogues']['1']},
                         {(1,1),(1,0),(1,-1),(0,1),(-1,1)})
        self.assertTrue(all(p['player']==0 for p in public))

    def test_recomputed_label_and_skill_change_after_removing_hidden_restriction(self):
        case=dict(name='old_favored',kind='B',skill='update',raw=fixture(schedule=(0,1)),
                  setup=[{'action':'PASS'}],events=[offer(1,actor=1)])
        task=tasks_from_case(case)
        self.assertEqual(task['teacher']['gold'],dict(possible_preferences=['want','neutral','avoid'],favored='undetermined'))
        self.assertEqual(task['skill'],'maintain')
        visible=str(request(task))
        for key in ('type_catalogues','joint_alternatives','preference_weights','action_values'):
            self.assertNotIn(key,visible)
        self.assertIn('public_preferences',visible)
        self.assertIn('preference_generation',visible)

    def test_favored_remains_teachable_with_full_three_value_support(self):
        tasks=[tasks_from_case(c) for c in extra_favored_cases()]
        self.assertEqual(tasks[0]['teacher']['gold'],dict(possible_preferences=['want','neutral'],favored='want'))
        self.assertEqual(tasks[2]['teacher']['gold'],dict(possible_preferences=['neutral','avoid'],favored='avoid'))
        self.assertEqual(tasks[1]['skill'],'maintain')
        self.assertEqual(tasks[3]['skill'],'maintain')
        self.assertAlmostEqual(tasks[0]['teacher']['preference_weights']['want'],2/3)
        self.assertTrue(all(t['teacher']['expansion']['new_worlds']==3 for t in tasks))

    def test_joint_unknowns_can_remove_favored_without_shrinking_set(self):
        tasks=[tasks_from_case(c) for c in joint_unknown_cases()]
        self.assertTrue(all(t['teacher']['expansion']['new_worlds']==5 for t in tasks))
        update=tasks[1]
        self.assertEqual(update['input']['previous_belief']['favored'],'want')
        self.assertEqual(update['teacher']['gold'],dict(possible_preferences=['want','neutral','avoid'],favored='undetermined'))
        self.assertEqual(update['skill'],'update')
        self.assertEqual(tasks[2]['skill'],'maintain')


if __name__=='__main__':unittest.main()
