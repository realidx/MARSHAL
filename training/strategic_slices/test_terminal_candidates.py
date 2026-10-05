"""Guard joint sampling and collective value semantics of the review format."""
from copy import deepcopy
import unittest
import numpy as np
from .terminal_candidates import validate_distribution, sample_member_world


def example():
    return dict(V_star=1.2,V_min=0.,C_span=1.2,
        information_channels=dict(query_answer=None,entry_and_future_public_history=.2),
        members=[dict(root_index=1,probability=.8,world_weights=[1.,0.],joint_world_masses=[.8,0.],
                      remaining_proposals=2,V_star=1.,V_min=0.,C_span=1.),
                 dict(root_index=2,probability=.2,world_weights=[0.,1.],joint_world_masses=[0.,.2],
                      remaining_proposals=1,V_star=2.,V_min=0.,C_span=2.)])


class TerminalCandidateTests(unittest.TestCase):
    def test_saved_nondefault_search_budgets_restore_the_same_reference(self):
        import tempfile
        from pathlib import Path
        from .build import sample_parent
        from .bounded import BoundedPrivateWindow
        from .common import save_reference
        from .terminal_candidates import restore_reference
        from training.b_sft.social_private_teacher import PrivateInvestigationRules
        from training.b_sft.preference_contract import world_weights
        raw=sample_parent(2026100703,2,rounds=1);rules=PrivateInvestigationRules(raw)
        tree=BoundedPrivateWindow(rules,rules.initial(),rules.worlds,
            world_weights=world_weights(rules.worlds,raw['background_prior']),lookahead_rr=3,
            max_joint_cells=8192,large_tree_ordered_sweeps=8,seconds=20).solve()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'reference.npz';save_reference(path,tree)
            restored=restore_reference(raw,dict(history=[],certificate=tree.certificate),path)
            self.assertEqual(restored.max_joint_cells,8192)
            self.assertEqual(restored.reference_identity()[0],tree.reference_identity()[0])

    def test_joint_history_world_correlation_is_preserved(self):
        row=example();rng=np.random.default_rng(4)
        samples=[sample_member_world(row,rng) for _ in range(3000)]
        self.assertEqual(set(samples),{(0,0),(1,1)})
        self.assertLess(abs(samples.count((0,0))/len(samples)-.8),.03)

    def test_singleton_uses_same_distribution_contract(self):
        row=example();row['members']=row['members'][:1]
        row['members'][0].update(probability=1.,joint_world_masses=[1.,0.])
        row.update(V_star=1.,C_span=1.)
        self.assertEqual(sample_member_world(row,np.random.default_rng(1)),(0,0))

    def test_equal_weighting_histories_is_rejected(self):
        row=example();row.update(V_star=1.5,C_span=1.5)
        with self.assertRaisesRegex(ValueError,'Collective value'):validate_distribution(row)

    def test_posterior_inconsistent_with_joint_mass_is_rejected(self):
        row=example();row['members'][0]['world_weights']=[.5,.5]
        with self.assertRaisesRegex(ValueError,'posterior'):validate_distribution(row)

    def test_unmeasured_channel_stays_null(self):
        row=example();original=deepcopy(row);validate_distribution(row)
        self.assertEqual(row,original);self.assertIsNone(row['information_channels']['query_answer'])

    def test_negative_and_nonfinite_mass_are_rejected(self):
        for masses in ([-.1,.9],[float('nan'),.8]):
            row=example();row['members'][0]['joint_world_masses']=masses
            with self.assertRaisesRegex(ValueError,'distribution'):validate_distribution(row)

    def test_terminal_neighborhood_is_enforced(self):
        row=example();row['members'][0]['remaining_proposals']=4
        with self.assertRaisesRegex(ValueError,'terminal neighborhood'):validate_distribution(row)

if __name__=='__main__':unittest.main()
