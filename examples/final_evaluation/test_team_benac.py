import json,tempfile,unittest
import io
from unittest.mock import patch
from pathlib import Path
from examples.final_evaluation.team_benac import load,team_game,summarize,complete
class TeamTests(unittest.TestCase):
 def test_invalid_schema_does_not_abort(self):
  _,resets=load()
  def generate(route,request):
   names={t['function']['name'] for t in request['tools']}
   name='PASS' if 'PASS' in names else 'REJECT'
   return dict(completion=dict(raw_message=dict(content='',tool_calls=[dict(function=dict(name=name,arguments='{"unexpected":true}'))]),finish_reason='tool_calls'))
  with tempfile.TemporaryDirectory() as d:
   rows=[team_game(r,dict(model='same',base_url='unused'),Path(d),generate) for r in resets]
  self.assertEqual(len(rows),16)
  self.assertTrue(all(r['status']=='invalid_action' for r in rows))
  self.assertTrue(all(r['invalid_calls']>0 and r['total_utility'] is None for r in rows))
  self.assertEqual(summarize(rows)['all/all']['complete'],0)
 def test_output_budget_matches_manifest(self):
  manifest,_=load()
  response=dict(choices=[dict(message=dict(content='ok'),finish_reason='stop')])
  with patch('examples.final_evaluation.team_benac.urlopen',return_value=io.StringIO(json.dumps(response))) as call:
   result=complete(dict(model='same',base_url='http://localhost/v1'),dict(messages=[],max_tokens=1024))
  sent=json.loads(call.call_args.args[0].data)
  self.assertEqual(sent['max_tokens'],4096)
  self.assertEqual(sent['max_tokens'],manifest['max_tokens'])
  self.assertEqual(result['request']['max_tokens'],4096)
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
