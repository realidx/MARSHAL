import unittest
from unittest.mock import patch
from collections import defaultdict
from training.social_mixed.paired_bank import load
from training.social_mixed.paired_requests import request
from training.social_mixed.stabilization import StableCollector
class PairedTests(unittest.TestCase):
 def test_views(self):
  groups=defaultdict(dict)
  for t in load():groups[t['canonical_id']][t['paired_view']]=t
  self.assertGreaterEqual(len(groups),36)
  for views in groups.values():
   self.assertEqual(set(views),{'O','B','Pplus'})
   self.assertEqual(views['O']['teacher'],views['Pplus']['teacher'])
   o=request(views['O']);p=request(views['Pplus'])
   self.assertTrue(p['messages'][1]['content'].startswith(o['messages'][1]['content']))
   self.assertNotIn('SUPPLIED BELIEF',o['messages'][1]['content'])
   self.assertEqual(o['tools'],p['tools'])
 def test_arms(self):
  def generate(reqs):return [dict(response_ids=[1],completion=dict(finish_reason='stop',value=i%2)) for i,_ in enumerate(reqs)]
  for arm,expected in [('outcome',{'O'}),('decomposed',{'O','B','Pplus'})]:
   c=StableCollector({'bp_train':load()},generate,concurrency=8)
   with patch('training.b_sft.social_bp_training.reward',side_effect=lambda t,c:dict(reward=c['value'],status='ok')):
    rows,_,_,m=c.collect(0,arm)
   self.assertEqual({r['kind'] for r in rows},expected)
   self.assertEqual(m['candidate_groups'],9)
   for d in expected:self.assertAlmostEqual(sum(r['task_weight'] for r in rows if r['kind']==d)/len(rows),1/len(expected))

class NativeReconstructionTests(unittest.TestCase):
 def test_supplied_belief_does_not_change_native_target(self):
  import json
  from copy import deepcopy
  from training.social_mixed.prepare_paired_bank import SOURCE
  from training.social_mixed.reconstruct_paired_bank import rebuild
  rows=map(json.loads,(SOURCE/'bp_train.jsonl').read_text().splitlines())
  t=next(t for t in rows if t['task']=='P' and t['kernel']=='P1')
  a=rebuild(t)
  self.assertEqual(a['status'],'reconstructed')
  changed=deepcopy(t);changed['input']['supplied_belief']={'arbitrary_oracle_information':'must never be consumed'}
  b=rebuild(changed)
  self.assertEqual(a['task']['teacher'],b['task']['teacher'])
  self.assertEqual(a['task']['input'],b['task']['input'])

class RepairTests(unittest.TestCase):
 def test_query_replays_keep_private_answers(self):
  import json
  from training.social_mixed.prepare_paired_bank import OUT
  records={r['source_sha256']:r for r in map(json.loads,(OUT/'reconstruction.jsonl').read_text().splitlines())}
  repaired=[r for r in records.values() if r.get('own_query_interventions')]
  self.assertEqual(len(repaired),20)
  for r in repaired:
   t=r['task'];teacher=t['teacher']
   self.assertAlmostEqual(sum(teacher['posterior']),1)
   for fact in t['input']['private_results']:
    value={'want':1,'neutral':0,'avoid':-1}[fact['preference']]
    for w,p in zip(teacher['worlds'],teacher['posterior']):
     if p>0:self.assertEqual(w[fact['player']][fact['goal']],value)

 def test_stale_flag_repair_and_dependency_rejection(self):
  import json
  from copy import deepcopy
  from training.social_mixed.prepare_paired_bank import SOURCE
  from training.social_mixed.reconstruct_paired_bank import rebuild
  t=next(t for t in map(json.loads,(SOURCE/'bp_train.jsonl').read_text().splitlines()) if t['task']=='P' and t['kernel']=='P1')
  changed=deepcopy(t)
  changed['input']['current_state']['goals'][0]['binary']=not changed['input']['game']['goals'][0]['binary']
  result=rebuild(changed)
  self.assertEqual(result['status'],'reconstructed')
  self.assertEqual(len(result['state_repairs']),1)
  changed['input']['current_state']['goals'][0]['required_actions']=[]
  self.assertEqual(rebuild(changed)['status'],'native_state_mismatch')

if __name__=='__main__':unittest.main()
