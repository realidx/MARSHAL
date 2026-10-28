import json,unittest
from pathlib import Path
from copy import deepcopy
import numpy as np
from training.b_sft.build_b3_external import build,fixture
from training.b_sft.social_private_teacher import PrivateEpisode,audit_native
from training.b_sft.shared_teacher import native
from training.b_sft.bp_semantics import semantic_id
from training.b_sft.social_named_probe import request

class ExternalB3Tests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.tasks,cls.requests,cls.checks,cls.unavailable=build()
 def test_counts_and_labels(self):
  self.assertEqual(len(self.tasks),12);self.assertFalse(self.unavailable)
  self.assertEqual(sum(t['completion_mode']=='linear' for t in self.tasks),6)
  self.assertEqual(sum(t['b3_role']=='external_update' for t in self.tasks),8)
 def test_evidence_is_external_not_own_response(self):
  for t in self.tasks:
   tr=t['teacher']['b3_audit']['trace']
   self.assertEqual([r['actor'] for r in tr],[1,0,0,1])
   self.assertTrue(tr[0]['joint_changed'])
   self.assertFalse(tr[1]['joint_changed']);self.assertFalse(tr[2]['joint_changed'])
 def test_cumulative_label_requires_first_evidence_in_both_scoring_modes(self):
  sensitive=[t for t in self.tasks if t['b3_role']=='external_update' and t['teacher']['b3_audit']['first_evidence_ablation']['label_changes']]
  self.assertEqual({t['completion_mode'] for t in sensitive},{'binary','linear'})
  self.assertEqual(len(sensitive),2)
 def test_linear_changes_inference_not_just_names(self):
  group=[t for t in self.tasks if t['b3_case']=='joint_favored' and t['input']['voluntary_history'][-1]['response']=='ACCEPT']
  self.assertEqual({t['teacher']['gold']['favored'] for t in group},{'avoid','neutral'})
 def test_fractional_completion_and_legacy_binary_guard(self):
  raw,_=fixture(2,False)
  with self.assertRaisesRegex(ValueError,'Binary reference only'):native(raw)
  e=PrivateEpisode(raw,[{'action':'PASS'}]);audit_native(e.tree)
  fractional=0
  for entry in e.tree.entries:
   if entry.actor is not None:continue
   c=entry.node.state.snapshot_commitments()
   progress=np.array([sum(c[a.player_id][a.action_id] for a in g.required_actions)/len(g.required_actions) for g in e.rules.spec.goals])
   np.testing.assert_allclose(progress,entry.node.state.goal_satisfaction())
   np.testing.assert_allclose(entry.payoff,np.array(e.tree.worlds)@progress)
   fractional+=int(any(0<x<1 for x in progress))
  self.assertGreater(fractional,0)
 def test_request_and_semantics_record_scoring(self):
  for t,r in zip(self.tasks,self.requests):
   text=r['request']['messages'][1]['content']
   self.assertEqual('LINEAR: fraction' in text,t['completion_mode']=='linear')
   self.assertEqual(r['request']['max_tokens'],1024)
   modified=deepcopy(t)
   for g in modified['input']['game']['goals']:g['binary']=not g['binary']
   self.assertNotEqual(semantic_id(t),semantic_id(modified))
 def test_old_binary_requests_unchanged(self):
  base=Path(__file__).resolve().parents[2]/'examples/social_bp/response_only_v1'
  rows={t['id']:t for t in map(json.loads,(base/'tasks.jsonl').read_text().splitlines())}
  for r in map(json.loads,(base/'requests.jsonl').read_text().splitlines()):
   t=rows[r['task_id']]
   self.assertEqual(request(t,'action_tools',t.get('name_variant',0)),r['request'])

if __name__=='__main__':unittest.main()
