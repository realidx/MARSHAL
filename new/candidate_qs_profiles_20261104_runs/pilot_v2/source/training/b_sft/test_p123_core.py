import json,unittest
from copy import deepcopy
from fractions import Fraction
import numpy as np
from training.b_sft.organize_p123 import build,read,OUT,SOURCE,PREVIOUS,stable
from training.b_sft.bp_semantics import semantic_id
from training.b_sft.social_named_probe import request,present,action_call
from training.b_sft.social_bp_training import reward
from training.b_sft.social_p_qualitative import robust_actions,WIDE_ENVELOPES

class P123CoreTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.bank,cls.assign,cls.target,cls.old,cls.new,cls.diag,cls.audits=build()
  cls.by={(t['kernel'],t['p123_case'],t['completion_mode']):t for t in cls.new+cls.diag}
 def get(self,k,c,m):return self.by[k,c,m]
 def gold(self,k,c,m):return self.get(k,c,m)['teacher']['acceptable_actions']
 def test_counts_and_no_all_correct_core(self):
  self.assertEqual((len(self.old),len(self.new),len(self.diag),len(self.audits)),(6,36,4,92))
  for t in self.new:
   self.assertGreater(len(t['teacher']['acceptable_actions']),0)
   self.assertLess(len(t['teacher']['acceptable_actions']),len(t['input']['legal_actions']))
   self.assertTrue(t['teacher']['p123_audit']['independent_terminal_payoffs'])
 def test_response_payoff_priority(self):
  for mode in ('binary','linear'):
   self.assertEqual(self.gold('P1','response_own_gain',mode),[{'response':'ACCEPT'}])
   self.assertEqual(self.gold('P1','response_own_loss',mode),[{'response':'REJECT'}])
   self.assertEqual(self.gold('P1','response_helpful_tie',mode),[{'response':'ACCEPT'}])
   self.assertEqual(self.gold('P1','response_net_compensation',mode),[{'response':'ACCEPT'}])
  self.assertEqual(self.gold('P1','response_harmful_tie','binary'),[{'response':'REJECT'}])
  self.assertEqual(self.gold('P1','response_harmful_tie','linear'),[{'response':'ACCEPT'}])
 def test_exact_beliefs_visible_and_values_recomputed(self):
  for t in self.new:
   if t['kernel']!='P2':continue
   rows=t['input']['supplied_belief']['joint_distribution'];w=np.array([float(Fraction(r['probability'])) for r in rows])
   self.assertAlmostEqual(w.sum(),1)
   a=t['teacher']['p123_audit'];np.testing.assert_allclose(w,a['supplied_weights'],atol=1e-9,rtol=0)
   for row,world in zip(rows,a['worlds']):
    for pref in row['preferences']:
     self.assertEqual({'want':1,'neutral':0,'avoid':-1}[pref['preference']],world[pref['player']][pref['goal']])
   np.testing.assert_allclose(np.einsum('awp,w->ap',a['per_world_payoffs'],w),t['teacher']['action_values'],atol=1e-9,rtol=0)
   text=request(t,'action_tools',t['name_variant'])['messages'][1]['content']
   self.assertEqual(text.count('- Probability '),len(rows));self.assertIn('do not multiply marginal',text)
 def test_joint_correlation_changes_action_with_same_marginals(self):
  for mode in ('binary','linear'):
   pair=[self.get('P2','joint_'+v,mode) for v in ('positive','negative')]
   marginals=[]
   for t in pair:
    a=t['teacher']['p123_audit'];marginals.append([[sum(p for p,w in zip(a['supplied_weights'],a['worlds']) if w[1][g]==v) for v in (1,0,-1)] for g in (0,1)])
   np.testing.assert_allclose(*marginals,atol=1e-9,rtol=0)
   self.assertFalse({stable(a) for a in pair[0]['teacher']['acceptable_actions']}&{stable(a) for a in pair[1]['teacher']['acceptable_actions']})
 def test_proposal_ties_do_not_apply_altruism(self):
  for mode,count in [('binary',2),('linear',3),('mixed',3)]:
   t=self.get('P2','weight_middle' if mode=='mixed' else 'weight_tie',mode)
   actions=t['input']['legal_actions'];values=np.array(t['teacher']['action_values']);keep=[actions.index(a) for a in t['teacher']['acceptable_actions']]
   self.assertEqual(len(keep),count);self.assertGreater(np.ptp(values[keep,1]),.1)
   np.testing.assert_allclose(values[keep,0],values[:,0].max())
 def test_qualitative_certificates_strict_and_ambiguous_excluded(self):
  for t in self.new+self.diag:
   if t['kernel']!='P3':continue
   g=t['teacher'];strict=robust_actions(g['per_world_payoffs'],0,g['worlds'],g['claims'],envelopes=WIDE_ENVELOPES)
   self.assertEqual(strict['acceptable'],g['qualitative_certificate']['acceptable'])
   if t in self.diag:
    self.assertEqual(strict['status'],'ambiguous_information')
    with self.assertRaisesRegex(ValueError,'No supported P target'):reward(t,{})
 def test_paired_inputs_and_weight_semantic_identity(self):
  def normalize(obj):
   if isinstance(obj,dict):return {k:True if k=='binary' else normalize(v) for k,v in obj.items()}
   if isinstance(obj,list):return [normalize(x) for x in obj]
   return obj
  pairs=0
  for t in self.new+self.diag:
   if t['completion_mode']!='binary' or t['p123_case']=='weight_tie':continue
   other=self.get(t['kernel'],t['p123_case'],'linear')
   self.assertEqual(normalize(t['input']),normalize(other['input']));pairs+=1
  self.assertEqual(pairs,17)
  a=self.get('P2','weight_low','binary');b=self.get('P2','weight_high','binary')
  self.assertNotEqual(semantic_id(a),semantic_id(b))
  c=deepcopy(a);c['input']['supplied_belief']['joint_distribution'].reverse()
  self.assertEqual(semantic_id(a),semantic_id(c))
 def test_all_legal_native_rewards_and_request_budget(self):
  for t in self.old+self.new:
   v=present(t,t['name_variant'])
   for native,named in zip(t['input']['legal_actions'],v['legal_actions']):
    name,args=action_call(named)
    completion=dict(raw_message=dict(content='Brief check.',tool_calls=[dict(function=dict(name=name,arguments=json.dumps(args)))]),finish_reason='stop')
    self.assertEqual(reward(t,completion)['reward'],int(native in t['teacher']['acceptable_actions']))
   req=request(t,'action_tools',t['name_variant']);self.assertEqual(req['max_tokens'],1024)
   for secret in ('p123_audit','action_values','policy_sha256','per_world_payoffs'):
    self.assertNotIn(secret,json.dumps(req))
 def test_holdout_B_P4_deferred_and_source_preserved(self):
  new=read(OUT/'bp_candidate_tasks.jsonl');old=read(PREVIOUS);indexed={t['id']:t for t in new}
  for t in old:
   a=self.assign.get(t['id'],{})
   if t['task']=='B' or t['split']!='train' or a.get('kernel')=='P4' or a.get('deferred'):
    self.assertEqual(indexed[t['id']],t)
  self.assertEqual(read(SOURCE),self.bank)
  held={t['family'] for t in self.bank if t['split']!='train'}
  self.assertFalse(held&{t['family'] for t in self.new})
  self.assertEqual(len(new),256)

if __name__=='__main__':unittest.main()
