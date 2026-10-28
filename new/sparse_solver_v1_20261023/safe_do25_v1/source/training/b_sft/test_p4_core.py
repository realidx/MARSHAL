import json,unittest
from copy import copy,deepcopy
from fractions import Fraction
import numpy as np
from training.b_sft.organize_p4 import build,read,OUT,SOURCE,PREVIOUS,fixture,stable,BASE_ID,query_report
from training.b_sft.social_private_teacher import PrivateEpisode
from training.b_sft.social_named_probe import request,present,action_call
from training.b_sft.social_bp_training import reward
from training.b_sft.build_bp_pilot import make_task

class P4CoreTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.source,cls.old,cls.all_tasks,cls.audits,cls.links=build()
  cls.core=[t for t in cls.all_tasks if not t.get('diagnostic_only')]
  cls.diag=[t for t in cls.all_tasks if t.get('diagnostic_only')]
 def get(self,case,mode):return next(t for t in self.core if t['p4_case']==case and t['completion_mode']==mode)
 def test_counts_and_actual_query_value(self):
  self.assertEqual((len(self.old),len(self.audits),len(self.core),len(self.diag)),(40,27,15,1))
  expected={'acquisition':[(4/3,1),(5/6,2/3)],'deadline':[(0,1),(0,1.5)],
   'target_selection':[(7/3,2),(11/6,5/3)],'opportunity_cost':[(0,3),(2.25,3)],
   'ordinary_alternative':[(1.5,5/3),(1.5,1.5)]}
  for case,values in expected.items():
   for mode,(query,ordinary) in zip(('binary','linear'),values):
    a=self.get(case,mode)['teacher']['p4_audit'];q=a['query_comparison']
    self.assertAlmostEqual(q['best_query_own'],query);self.assertAlmostEqual(q['best_ordinary_own'],ordinary)
    gain=a['answer_use_ablation']['own_answer_use_gain']
    self.assertAlmostEqual(gain,query-ordinary if case in ('acquisition','target_selection') else 0)
 def test_target_query_distinguishes_two_unknown_preferences(self):
  for mode in ('binary','linear'):
   t=self.get('target_selection',mode);u=t['input']['supplied_belief']['unresolved_preferences']
   self.assertEqual(u,[{'player':1,'goal':0},{'player':1,'goal':5}])
   self.assertEqual(t['teacher']['acceptable_actions'],[{'action':'INVESTIGATE','player':1,'goal':0}])
   audit=t['teacher']['p4_audit'];values={r['action']['goal']:r['own_value'] for r in audit['query_comparison']['query_values']}
   self.assertGreater(values[0]-values[5],.1)
   self.assertAlmostEqual(audit['irrelevant_answer_ablation']['own_answer_use_gain'],0)
   c=t['input']['current_state']['commitments'];goal=t['input']['game']['goals'][5]
   self.assertTrue(all(c[a['player_id']][a['action_id']] for a in goal['required_actions']))
 def test_followups_are_same_public_state_and_all_results_count(self):
  by={t['id']:t for t in self.all_tasks}
  for link in self.links:
   parent=by[link['parent']];children=[by[i] for i in link['children']]
   self.assertEqual({t['teacher']['p4_audit']['result_value'] for t in children},{1,0,-1})
   self.assertEqual(len({stable(t['input']['current_state']) for t in children}),1)
   self.assertEqual(len({stable(t['input']['public_preferences']) for t in children}),1)
   self.assertFalse(set.intersection(*[{stable(a) for a in t['teacher']['acceptable_actions']} for t in children]))
   total=np.zeros(2)
   for t in children:
    a=t['teacher']['p4_audit'];self.assertAlmostEqual(a['result_probability'],1/3)
    total+=a['result_probability']*np.array(a['conditional_policy_value'])
    self.assertEqual(len(t['input']['private_results']),1)
    self.assertFalse(any(a.get('action')=='INVESTIGATE' for a in t['input']['legal_actions']))
   np.testing.assert_allclose(total,parent['teacher']['p4_audit']['answer_use_ablation']['informed_value'],atol=1e-9,rtol=0)
 def test_uninformative_branch_diagnostic_only(self):
  t=self.diag[0]
  self.assertEqual((t['completion_mode'],t['teacher']['p4_audit']['result_value']),('linear',-1))
  self.assertEqual(t['teacher']['acceptable_actions'],t['input']['legal_actions'])
  self.assertFalse(t['training_ready'])
  self.assertNotIn(t['id'],{r['task_id'] for r in read(OUT/'requests.jsonl')})
  self.assertNotIn(t['id'],{r['id'] for r in read(OUT/'bp_candidate_tasks.jsonl')})
  bank={x['id']:x for x in self.source};raw,public,setup,_=fixture(bank,'acquisition','linear')
  e=PrivateEpisode(raw,setup);q=dict(action='INVESTIGATE',player=1,goal=0);e.observe(q)
  self.assertIsNone(make_task(e,public,setup,[q],'P',1,t['family'],facts=[(1,0,-1)],pool='result_use'))
 def test_ties_neither_forced_investigation_nor_forced_rejection(self):
  t=self.get('ordinary_alternative','linear');a=t['teacher']['acceptable_actions']
  self.assertTrue(any(x.get('action')=='INVESTIGATE' for x in a))
  self.assertTrue(any(x.get('action')!='INVESTIGATE' for x in a))
  self.assertFalse(t['information_positive']);self.assertIsNone(t['information_negative_kind'])
 def test_fixture_no_source_mutation_and_deadline_control(self):
  bank={t['id']:deepcopy(t) for t in self.source};before=deepcopy(bank)
  for mode in ('binary','linear'):
   a,_,sa,_=fixture(bank,'acquisition',mode);b,_,sb,_=fixture(bank,'deadline',mode)
   self.assertEqual(sa,sb);a['game']['round_robin']=b['game']['round_robin'];self.assertEqual(a,b)
   fixture(bank,'target_selection',mode)
  self.assertEqual(before,bank)
 def test_private_result_and_quota_audit(self):
  for t in self.core:
   if t['p4_role']!='acquisition_decision':continue
   p=t['teacher']['p4_audit']['privacy']
   for k in ('public_state_identical_across_answers','answer_only_to_investigator','other_players_quotas_unchanged','commitments_unchanged','one_opportunity_consumed'):
    self.assertTrue(p[k])
   self.assertGreaterEqual(p['worlds_checked'],3)
 def test_all_legal_rewards_and_prompt_budget(self):
  for t in self.core+self.diag:
   visible=present(t,t['name_variant'])
   for native,named in zip(t['input']['legal_actions'],visible['legal_actions']):
    name,args=action_call(named)
    c=dict(raw_message=dict(content='Decision checked.',tool_calls=[dict(function=dict(name=name,arguments=json.dumps(args)))]),finish_reason='stop')
    self.assertEqual(reward(t,c)['reward'],int(native in t['teacher']['acceptable_actions']))
   req=request(t,'action_tools',t['name_variant']);self.assertEqual(req['max_tokens'],1024)
   for secret in ('own_query_margin','p4_audit','informed_value','result_blind_value','action_values'):
    self.assertNotIn(secret,json.dumps(req))
 def test_unrelated_candidate_and_heldout_unchanged(self):
  previous=read(PREVIOUS);new=read(OUT/'bp_candidate_tasks.jsonl');by={t['id']:t for t in new}
  removed={t['id'] for t in self.old if t['split']=='train'}
  for t in previous:
   if t['id'] not in removed:self.assertEqual(by[t['id']],t)
  self.assertEqual(len(new),244);self.assertEqual(len(by),len(new))
  self.assertEqual(read(SOURCE),self.source)
  held={t['family'] for t in self.source if t['split']!='train'}
  self.assertFalse(held&{t['family'] for t in self.core})

if __name__=='__main__':unittest.main()
