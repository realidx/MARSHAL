from types import SimpleNamespace
import unittest
from examples.strategic_slices.select_terminal_d_v4 import choose


class SelectionTests(unittest.TestCase):
    def test_train_only_protected_groups_and_no_complete_only_filter(self):
        rows=[];parents={};metrics={};measured={}
        for i in range(105):
            cid=f'{i:03d}';pid=f'p{i//3:02d}'
            parents[pid]=dict(players=2 if i//3%2 else 3)
            rows.append(dict(id=cid,parent_id=pid,family=pid,split='train',k=i%3+1,
                decision_kind='proposal' if i%2 else 'response',C_span=1.,
                information_channels=dict(query_answer=.1 if i==0 else 0.)))
            metrics[cid]=dict(completed=7 if i%2 else 8,decision_gap_or_completion_contrast=True,
                any_step_value_contrast=True,mixed_completion=bool(i%2),
                decision_gap_span_completed=.2,strong_acquisition=i==0)
            measured[cid]=dict(D_completed_only=dict(mean=.3))
        # Held-out records deliberately have no metrics, and must not be read.
        rows.append(dict(id='test',parent_id='test',family='test',split='test',k=3,
            decision_kind='proposal',C_span=100,information_channels=dict(query_answer=100)))
        groups=[dict(split='train',candidate_ids=[f'{i:03d}' for i in range(j,j+3)]) for j in (0,3,6)]
        for row in rows[:9]:row['family']='protected-family'
        data=SimpleNamespace(candidates=rows,parents=parents,entry_answer_relations=groups)
        # Protected members remain together even without measured contrast.
        for cid in [cid for group in groups for cid in group['candidate_ids']]:
            metrics[cid].update(decision_gap_or_completion_contrast=False,any_step_value_contrast=False)
        selected,report=choose(data,metrics,measured)
        ids={r['id'] for r in selected}
        self.assertEqual(len(ids),100)
        self.assertTrue({cid for group in groups for cid in group['candidate_ids']}<=ids)
        self.assertNotIn('test',ids)
        self.assertTrue(any(metrics[cid]['completed']<8 for cid in ids))
        self.assertEqual(report['protected'],9)
        self.assertEqual(report['family_cap_exceptions'],{'protected-family':9})
        self.assertEqual(report['relative_optimality_gap'],0)


if __name__=='__main__':unittest.main()
