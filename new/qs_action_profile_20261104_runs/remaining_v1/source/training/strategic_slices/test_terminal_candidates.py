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

    def test_expanded_entrance_keeps_local_decision_limit(self):
        from .terminal_candidates import LOCAL_DECISION_ENTRANCE_CONTRACT
        row=example();row.update(entrance_contract=LOCAL_DECISION_ENTRANCE_CONTRACT,k=2)
        row['members'][0]['remaining_proposals']=4
        validate_distribution(row)
        row['k']=4
        with self.assertRaisesRegex(ValueError,'k=1/2/3'):validate_distribution(row)

    def test_manifest_must_authorize_expanded_initial_terminal_scope(self):
        import tempfile
        from pathlib import Path
        from .common import write_json, write_rows
        from .terminal_candidates import TerminalCandidates, VERSION, LOCAL_DECISION_ENTRANCE_CONTRACT
        row=example();row.update(id='a',parent_id='p',reference_id='r',family='f',split='train',
            entrance_contract=LOCAL_DECISION_ENTRANCE_CONTRACT,k=2)
        row['members'][0]['remaining_proposals']=4
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            manifest=dict(version=VERSION,files={})
            write_json(root/'manifest.json',manifest)
            write_rows(root/'parents.jsonl',[dict(id='p',family='f',split='train',raw=dict(game=dict(round_robin=[0,1,0,1])))])
            write_rows(root/'references.jsonl',[dict(id='r',parent_id='p',history=[0],
                belief_regime='initial-prior-plus-reference-reach',certificate=dict(verified=True,cutoff_leaves=0,remaining_game_terminal_scope=True))])
            write_rows(root/'candidates.jsonl',[row])
            with self.assertRaisesRegex(ValueError,'contract differs'):TerminalCandidates(root)
            manifest.update(entrance_contract=LOCAL_DECISION_ENTRANCE_CONTRACT)
            write_json(root/'manifest.json',manifest)
            with self.assertRaisesRegex(ValueError,'initial terminal reference'):TerminalCandidates(root)

    def test_loader_guards_collective_answer_relations(self):
        import tempfile
        from pathlib import Path
        from .common import write_json, write_rows
        from .terminal_candidates import TerminalCandidates, VERSION
        rows=[];members=[]
        for i,cid in enumerate(('a','b')):
            weights=[0.,0.];weights[i]=1.
            member=dict(root_index=1,history=[],probability=1.,world_weights=weights,
                        joint_world_masses=weights,remaining_proposals=1,
                        V_star=1.,V_min=0.,C_span=1.,root_Q=weights)
            rows.append(dict(id=cid,parent_id='p',reference_id='r',split='train',family='f',
                             ego=0,k=1,V_star=1.,V_min=0.,C_span=1.,members=[member],
                             information_channels=dict(query_answer=0.)))
            members.append(dict(member,candidate_id=cid,probability=.5,
                                joint_world_masses=[v*.5 for v in weights]))
        relation=dict(id='g',candidate_ids=['a','b'],members=members,parent_id='p',
                      reference_id='r',split='train',ego=0,root_index=1,epsilon=.1,
                      V_full=1.,V_masked=.5,S=.5,must_change_pairs=[[0,1]])
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)
            write_json(p/'manifest.json',dict(version=VERSION,files={}))
            write_rows(p/'parents.jsonl',[dict(id='p',family='f',split='train')])
            write_rows(p/'references.jsonl',[dict(id='r',parent_id='p')])
            write_rows(p/'candidates.jsonl',rows)
            write_rows(p/'entry_answer_relations.jsonl',[relation])
            self.assertEqual(len(TerminalCandidates(p).entry_answer_relations),1)
            write_rows(p/'entry_answer_relations.jsonl',[dict(relation,candidate_ids=['a','missing'])])
            with self.assertRaisesRegex(ValueError,'lost a member'):TerminalCandidates(p)
            write_rows(p/'entry_answer_relations.jsonl',[dict(relation,S=0.)])
            with self.assertRaisesRegex(ValueError,'information value mismatch'):TerminalCandidates(p)

if __name__=='__main__':unittest.main()
