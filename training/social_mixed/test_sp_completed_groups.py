import unittest
from training.social_mixed.reasoning_training import assign_sp_completed_advantages

class CompletedSPTests(unittest.TestCase):
    def check_groups(self, groups):
        units=[]; rows=[]
        for group,values in enumerate(groups):
            for value in values:
                key=str(len(units))
                units.append(dict(unit=key,group=str(group),utility=value))
                rows.append(dict(unit=key,protocol_failure=None,protocol_advantage=0.,loss_weight=1.))
        metrics={}
        assign_sp_completed_advantages(rows,units,metrics)
        return rows,metrics

    def test_partial_group_keeps_contrast(self):
        rows,m=self.check_groups([[1.,None,0.,None]])
        for row,expected in zip(rows,[1.,0.,-1.,0.]):
            self.assertAlmostEqual(row['task_advantage'],expected,places=5)
        self.assertEqual(m['selfplay/completed_mixed_groups'],1)

    def test_groups_do_not_mix_and_singletons_are_zero(self):
        rows,_=self.check_groups([[1.,1.,None,None],[0.,0.,0.,0.],[3.,None,None,None],[None]*4])
        self.assertTrue(all(r['task_advantage']==0 for r in rows))

    def test_protocol_penalty_preserved(self):
        rows=[dict(unit=str(i),protocol_failure='truncated' if i==1 else None,
                   protocol_advantage=-.2 if i==1 else 0.,loss_weight=2.) for i in range(3)]
        units=[dict(unit=str(i),group='reset:seat',utility=v) for i,v in enumerate([1.,None,0.])]
        assign_sp_completed_advantages(rows,units,{})
        self.assertEqual(rows[1]['advantage'],-.2)
        self.assertEqual(rows[1]['protocol_weight'],2.)
        self.assertEqual(rows[1]['kl_weight'],2.)

if __name__=='__main__':unittest.main()
