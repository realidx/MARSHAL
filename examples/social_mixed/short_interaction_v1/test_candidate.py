import json,random,unittest
from pathlib import Path
from training.social_mixed.short_interaction import ShortInteraction,decision_request,decode_action,trajectory_advantages,collect_group
from training.social_mixed.b_direct_candidate import request as b_request
from training.social_mixed.paired_requests import request as old_request
from training.b_sft import social_named_probe as named
TASKS=list(map(json.loads,Path('examples/social_mixed/compact_bank_200/tasks.jsonl').read_text().splitlines()))
class CandidateTests(unittest.TestCase):
 def test_native_rollout_and_tools(self):
  task=next(t for t in TASKS if t['id']=='00bf2cbba65a880234f0-O')
  env=ShortInteraction(task,seconds=10,max_nodes=30000,max_sweeps=128)
  results=[]
  for seed in range(8):
   rng=random.Random(seed)
   def agent(inp):
    req=decision_request(inp)
    self.assertNotIn('SUPPLIED BELIEF',req['messages'][1]['content'])
    self.assertNotIn('0.1 goal-completion',req['messages'][1]['content'])
    self.assertNotIn('teacher',inp)
    actions=named.present(dict(task='P',skill='history_action',input=inp))['legal_actions']
    j=rng.randrange(len(actions));name,args=named.action_call(actions[j])
    completion=dict(raw_message=dict(tool_calls=[dict(function=dict(name=name,arguments=json.dumps(args)))]))
    self.assertEqual(decode_action(inp,completion),inp['legal_actions'][j])
    return decode_action(inp,completion)
   r=env.rollout(agent,seed);self.assertEqual(r['status'],'terminal');self.assertLessEqual(r['ego_decisions'],3)
   for first,second in zip(r['decisions'],r['decisions'][1:]):
    self.assertIn(first['action'],second['input']['voluntary_history'][len(first['input']['voluntary_history']):])
   results.append(r)
  self.assertAlmostEqual(sum(trajectory_advantages(results)),0)
  def complete(req):
   tool=req['tools'][0]['function']
   return dict(raw_message=dict(tool_calls=[dict(function=dict(name=tool['name'],arguments=json.dumps(tool['parameters']['enum'][0])))]))
  group=collect_group(env,complete,size=8)
  self.assertEqual(group['status'],'complete')
  self.assertEqual(len(group['trajectory_advantages']),8)
  self.assertTrue(all(len(r['calls'])==r['ego_decisions'] for r in group['trajectories']))
  failed=collect_group(env,lambda req:dict(raw_message=dict(content=''),finish_reason='length'),size=2)
  self.assertIsNone(failed['trajectory_advantages'])
  invalid=env.rollout(lambda inp:{'action':'NOT_AN_ACTION'})
  self.assertIsNone(invalid['terminal_utility'])
  with self.assertRaises(ValueError):trajectory_advantages([invalid])
 def test_b_contract(self):
  for t in TASKS:
   if t['paired_view']!='B':continue
   old=old_request(t);new=b_request(t)
   self.assertEqual(old['tools'],new['tools'])
   self.assertEqual(old['max_tokens'],new['max_tokens'])
   text='\n'.join(m['content'] for m in new['messages'])
   self.assertIn('Briefly explain, then submit exactly one SUBMIT_BELIEFS call.',text)
   self.assertEqual(old['messages'][0],new['messages'][0])
   self.assertEqual(old,b_request(t,clarify_semantics=False))
   self.assertIn('exactly the preferences compatible',text)
   self.assertIn('10 percentage points',text)
   self.assertIn('BELIEF SEMANTICS',text)
   self.assertNotIn('BELIEF SEMANTICS','\n'.join(m['content'] for m in b_request(t,clarify_semantics=False)['messages']))
if __name__=='__main__':unittest.main()
