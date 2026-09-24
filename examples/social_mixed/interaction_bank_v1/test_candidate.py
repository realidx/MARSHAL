import json,unittest
from pathlib import Path
from collections import Counter
from training.social_mixed.interaction_training import InteractionCollector
from training.b_sft.social_bp_training import native_completion
from training.social_mixed.reasoning_scoring import score
from training.social_mixed.paired_requests import request
ROOT=Path(__file__).resolve().parent
class CandidateTests(unittest.TestCase):
 def test_bank(self):
  ts=list(map(json.loads,(ROOT/'tasks.jsonl').read_text().splitlines()))
  old=list(map(json.loads,Path('examples/social_mixed/compact_bank_200/tasks.jsonl').read_text().splitlines()))
  self.assertEqual(Counter(t['paired_view'] for t in ts),dict(O=200,B=200,Pplus=200))
  self.assertEqual({t['id']:t for t in ts if t['paired_view']=='Pplus'},{t['id']:t for t in old if t['paired_view']=='Pplus'})
  self.assertEqual(sum(t.get('training_mode')=='short_interaction' for t in ts),100)
  for kind in ('B','O'):
   inputs=[json.dumps(t['input'],sort_keys=True) for t in ts if t['paired_view']==kind]
   self.assertEqual(len(inputs),len(set(inputs)))
  new=[t for t in ts if t.get('source')=='learning-structure-variant-v1']
  self.assertEqual(len(new),20)
  self.assertEqual(len(set(t['structure_prototype'] for t in new)),7)
  for t in new:
   self.assertTrue(score(t,native_completion(t))['correct'])
   self.assertIn('Briefly explain',request(t)['messages'][1]['content'])
   self.assertEqual(t['split'],'train')
 def test_collector(self):
  ts=list(map(json.loads,(ROOT/'tasks.jsonl').read_text().splitlines()))
  # Deterministic legal tool generator tests plumbing, not model learning.
  known={request(t)['messages'][1]['content']:native_completion(t) for t in ts if t.get('training_mode')!='short_interaction'}
  def generate(reqs):
   out=[]
   for req in reqs:
    f=req['tools'][0]['function'];schema=f['parameters']
    comp=known.get(req['messages'][1]['content'])
    if comp is None:comp=dict(raw_message=dict(tool_calls=[dict(function=dict(name=f['name'],arguments=json.dumps(schema['enum'][0])))]),finish_reason='stop')
    out.append(dict(completion=comp,response_ids=[1,2],prompt_ids=[3],behavior_log_probs=[-.1,-.2],finish_reason='stop'))
   return out
  c=InteractionCollector(ts,generate);rows,units,_,metrics=c.collect('outcome')
  self.assertEqual(len(units),32);self.assertEqual(metrics['short_groups'],2)
  self.assertAlmostEqual(sum(r['task_weight'] for r in rows)/len(rows),1.)
  for unit in units:
   rs=[r for r in rows if r['unit']==unit['unit']]
   self.assertEqual(len({r['task_advantage'] for r in rs}),1)
   self.assertAlmostEqual(sum(r['task_weight'] for r in rs)/len(rows),1/32)
  d=InteractionCollector(ts,generate);d.restore(c.state)
  self.assertEqual(d.state,c.state)
  d=InteractionCollector(ts,generate)
  rows,units,_,metrics=d.collect('decomposed')
  self.assertEqual(len(units),96)
  for kind in ('O','B','Pplus'):
   self.assertAlmostEqual(sum(r['task_weight'] for r in rows if r['kind']==kind)/len(rows),1/3)
  self.assertEqual(sum(x['count'] for k,x in d.state['coverage'].items() if k.startswith('Pplus:')),4)
if __name__=='__main__':unittest.main()
