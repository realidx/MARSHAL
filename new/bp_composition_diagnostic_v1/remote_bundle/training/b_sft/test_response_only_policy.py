import unittest
import numpy as np
from training.b_sft.decision_policy import optimal_indices
from training.b_sft.social_bp_curriculum import acceptable
from training.b_sft.social_p_qualitative import robust_actions
from training.b_sft.build_b_response_bridges import fixture
from training.b_sft.social_private_teacher import PrivateEpisode
from training.b_sft.debug.audit_readable_pretraining import independent_backward

class ResponseOnlyPolicyTests(unittest.TestCase):
    def test_only_responses_use_other_utility(self):
        values=[[0,0],[0,1],[0,2]]
        proposals=[{'action':'PASS'},{'action':'OFFER'},{'action':'INVESTIGATE'}]
        self.assertEqual(optimal_indices(values,0,proposals).tolist(),[0,1,2])
        self.assertEqual(acceptable(values,0,actions=proposals),[0,1,2])
        responses=[{'response':'REJECT'},{'response':'ACCEPT'}]
        self.assertEqual(optimal_indices(values[:2],0,responses).tolist(),[1])
        self.assertEqual(optimal_indices([[0,0],[-1,100]],0,responses).tolist(),[0])
        self.assertEqual(optimal_indices([[0,0],[0,0]],0,responses).tolist(),[0,1])
        self.assertEqual(optimal_indices([[0,0],[0,-1]],0,responses).tolist(),[0])

    def test_private_solver_does_not_prefer_helpful_offer(self):
        raw,_=fixture('coupled_payoffs','net_payoff')
        raw['type_catalogues']['1']=[[0,1]]
        e=PrivateEpisode(raw,[{'action':'PASS'}])
        row=e.choices(raw['own_preferences'])
        np.testing.assert_allclose(row['probabilities'],1/len(row['actions']))
        self.assertTrue(independent_backward(e.tree))
        self.assertEqual(e.tree.certificate['objective_version'],'response-only-altruism-v1')

    def test_qualitative_labels_distinguish_decision_stage(self):
        worlds=(((1,),),((-1,),))
        values=np.array([[[0,0],[0,0]],[[0,1],[0,1]]])
        self.assertEqual(robust_actions(values,0,worlds,[])['acceptable'],[0,1])
        self.assertEqual(robust_actions(values,0,worlds,[],offer_response=True)['acceptable'],[1])

if __name__=='__main__':unittest.main()
