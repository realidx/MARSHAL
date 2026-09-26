import json,random,tempfile,unittest
from pathlib import Path
from examples.final_evaluation.team_benac import load,team_game,summarize
from examples.final_evaluation.adversarial_runtime import play
from examples.final_evaluation.team_oracle import compile_policy,Controller
from training.social_mixed.core import Episode,sp_prompt

class SizeTests(unittest.TestCase):
 def test_sizes_and_native_rollouts(self):
  for n in (2,4):
   _,resets=load(Path(f'examples/final_evaluation/team_benac_{n}p_v1'))
   self.assertEqual(len(resets),16)
   rng=random.Random(42)
   def generate(route,request):
    tools=request['tools'];tool=rng.choice(tools)['function'];args=rng.choice(tool['parameters'].get('enum',[{}]))
    return dict(completion=dict(raw_message=dict(content='',tool_calls=[dict(function=dict(name=tool['name'],arguments=json.dumps(args)))]),finish_reason='tool_calls'))
   with tempfile.TemporaryDirectory() as d:rows=[team_game(r,{},Path(d),generate) for r in resets]
   self.assertTrue(all(r['status']=='terminal' for r in rows))
   self.assertEqual(len(summarize(rows)['all/all']['conditional_per_player']),n)
   for r in resets:
    self.assertEqual(len(r['raw']['game']['round_robin']),n*r['rounds'])
    if r['background_profile']=='avoid_heavy':self.assertEqual(r['raw']['preference_generation']['background_prior']['weights'],dict(want=1,neutral=1,avoid=2))
 def test_reference_information_and_offpath(self):
  _,rows=load(Path('examples/final_evaluation/team_benac_2p_v1'))
  r=json.loads(json.dumps(rows[0]));r['raw']['game']['round_robin']=[0,1];r['rounds']=1
  r['raw']['game']['goals']=r['raw']['game']['goals'][:1];r['realized_world']=[[1],[1]]
  policy=compile_policy(r,seconds=15,max_nodes=1000)
  self.assertGreater(policy['information_checks'],0)
  # Traverse all actions, including zero-reference-probability focal deviations.
  for seat in (0,1):
   ep=Episode(r,r['id'],0,42);controller=Controller(policy,seat,42)
   e=policy['nodes'][0]
   for ai,action in enumerate(e['actions']):
    branch=Controller(policy,seat,42);branch.observe(action)
    self.assertEqual(branch.index,e['children'][ai])
   response=controller.choose(ep);ep.accept(response);self.assertTrue(ep.calls[-1]['valid'])
  with tempfile.TemporaryDirectory() as d:
   def reject(route,request):
    names={x['function']['name'] for x in request['tools']};name='PASS' if 'PASS' in names else 'REJECT'
    return dict(completion=dict(raw_message=dict(content='',tool_calls=[dict(function=dict(name=name,arguments='{}'))]),finish_reason='tool_calls'))
   for seat in (0,1):
    result=play(r,seat,0,dict(q0={},focal={}),Path(d),reject,oracle=Controller(policy,seat,42))
    self.assertEqual(result[0]['status'],'terminal')
if __name__=='__main__':unittest.main()
