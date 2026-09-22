from contextlib import redirect_stdout
from copy import deepcopy
import io,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from examples.final_evaluation.shapefactory import Factory,IDS,instances,validate
from examples.final_evaluation.shapefactory_references import audit,action
from examples.final_evaluation.shapefactory_local import run_one

class ShapeTests(unittest.TestCase):
    def test_balanced_roles(self):
        from collections import Counter
        counts=Counter();shapes=Counter()
        for case in instances():
            repeated=next(s for s,n in Counter(case['specialties'].values()).items() if n==2)
            shapes[repeated]+=1
            for a,s in case['specialties'].items():counts[a]+=int(s==repeated)
        self.assertEqual(set(counts.values()),{6});self.assertEqual(set(shapes.values()),{4})
    def test_references(self):
        self.assertEqual(len(audit()),24)
    def test_private_information(self):
        for condition in (False,True):
            e=Factory(instances()[0],condition);o=e.observation('A')
            for a in 'BCD':
                row=o['task']['participants'][a]
                self.assertNotIn('tasks',row);self.assertNotIn('in_production',row)
                self.assertEqual('money' in row,condition)
            e.submit('B',action('message',channel='direct',recipients=['C'],content='secret'))
            self.assertEqual(e.observation('A')['events'],[])
            self.assertEqual(len(e.observation('C')['events']),1)
    def test_delayed_inventory_and_no_automatic_fulfillment(self):
        e=Factory(instances()[0]);shape=e.case['orders']['A'][0]
        e.submit('A',action('produce_shape',shape=shape,quantity=1))
        e.tick(2);self.assertEqual(e.state.task_state['participants']['A']['inventory'],[])
        e.tick(3);p=e.state.task_state['participants']['A']
        self.assertEqual(p['inventory'],[shape]);self.assertEqual(p['order_progress'],0);self.assertEqual(p['money'],160)
    def test_invalid_actions(self):
        self.assertIsNotNone(validate(action('fulfill_order',order_indices=[0,0])))
        self.assertIsNotNone(validate(action('propose_trade_offer',shape='circle',quantity=1,price_per_unit=101,target_id='B',offer_type='sell')))
        e=Factory(instances()[0]);self.assertFalse(e.submit('A',action('trade_response',transaction_id='fake',response_type='accept')))
    def test_complete_runner_noop_72_calls_and_logs(self):
        body=json.dumps(dict(choices=[dict(finish_reason='stop',message=dict(content=json.dumps(dict(action=action('do_nothing')))))] )).encode()
        with tempfile.TemporaryDirectory() as tmp,patch('examples.final_evaluation.shapefactory_local.urlopen',side_effect=lambda *a,**k:io.BytesIO(body)),redirect_stdout(io.StringIO()):
            r=run_one((instances()[0],'private',{},str(Path(tmp)/'game'),dict(model='test',base_url='http://127.0.0.1/v1')))
            self.assertEqual(r['calls'],72);self.assertEqual(r['metrics']['mean_final_balance'],200);self.assertEqual(r['metrics']['completed_fraction'],0)
            self.assertTrue((Path(tmp)/'game/COMPLETE').exists())
    def test_one_retry_then_failure_still_counts(self):
        body=json.dumps(dict(choices=[dict(finish_reason='stop',message=dict(content='bad'))])).encode()
        with tempfile.TemporaryDirectory() as tmp,patch('examples.final_evaluation.shapefactory_local.urlopen',side_effect=lambda *a,**k:io.BytesIO(body)),redirect_stdout(io.StringIO()):
            r=run_one((instances()[0],'private',{},str(Path(tmp)/'game'),dict(model='test',base_url='http://127.0.0.1/v1')))
            self.assertEqual(r['calls'],144);self.assertEqual(r['strict_format_failures'],144);self.assertEqual(r['metrics']['completed_fraction'],0)

if __name__=='__main__':unittest.main()
