import json,tempfile,unittest
from pathlib import Path
from examples.final_evaluation.team_benac import load,team_game,summarize
class TeamTests(unittest.TestCase):
 def test_native_complete(self):
  _,resets=load();seen=[]
  def generate(route,request):
   seen.append(route)
   names={t['function']['name'] for t in request['tools']}
   name='PASS' if 'PASS' in names else 'REJECT'
   return dict(completion=dict(raw_message=dict(content='',tool_calls=[dict(function=dict(name=name,arguments='{}'))]),finish_reason='tool_calls'))
  with tempfile.TemporaryDirectory() as d:
   route=dict(model='same',base_url='unused');rows=[team_game(r,route,Path(d),generate) for r in resets]
  self.assertEqual(len(rows),16);self.assertTrue(all(r['status']=='terminal' for r in rows));self.assertTrue(all(x==route for x in seen));self.assertEqual(summarize(rows)['all/all']['complete'],16)
  for r in rows:self.assertEqual(r['team_bounds'],[r['total_utility']]*2)
if __name__=='__main__':unittest.main()
