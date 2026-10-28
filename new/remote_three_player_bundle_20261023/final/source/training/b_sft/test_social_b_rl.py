import argparse
import json
from pathlib import Path
import tempfile
import unittest
from training.b_sft.social_b_rl import reward, prepare, probe, analyze
from training.b_sft.test_social_b_evaluation import task, completion
from training.b_sft.test_run_social_b_eval import mock_http, response

class RLPreparationTests(unittest.TestCase):
    def test_exact_reward_and_masks(self):
        t=task('a',[],['neutral'])
        self.assertEqual(reward(t,completion(['neutral']))['reward'],1)
        self.assertEqual(reward(t,completion(['want','neutral','avoid']))['reward'],0)
        self.assertEqual(reward(t,dict(message=dict(content='SUBMIT_BELIEFS({})')))['reward'],-1)
        self.assertEqual(reward(t,dict(completion(['neutral']),finish_reason='length'))['reward'],-1)
        self.assertIsNone(reward(t,dict(status='infrastructure_failure'))['reward'])
        t['input']['queries'].append(dict(player=1,goal=1))
        t['gold']['judgments'].append(dict(player=1,goal=1,possible_preferences=['avoid'],favored='avoid'))
        c=completion(['neutral']);args=json.loads(c['message']['tool_calls'][0]['function']['arguments'])
        args['judgments'].append(dict(player=1,goal=1,possible_preferences=['want'],favored='want'))
        c['message']['tool_calls'][0]['function']['arguments']=json.dumps(args)
        self.assertEqual(reward(t,c)['reward'],.5)

    def test_preparation_probe_no_gold_in_requests_and_explicit_sampling(self):
        with tempfile.TemporaryDirectory() as root:
            data=Path(root)/'data';data.mkdir()
            ts=[dict(task(str(i),[],['neutral']),family=str(i),split=s) for i,s in enumerate(['train','validation','test'])]
            (data/'tasks.jsonl').write_text(''.join(json.dumps(t)+'\n' for t in ts))
            (data/'pairs.jsonl').write_text(json.dumps(dict(before='0',after='0',category='update'))+'\n')
            prep=Path(root)/'prepared';manifest=prepare(data,prep)
            self.assertEqual(manifest['split_counts'],dict(train=1,validation=1,test=1))
            self.assertNotIn('gold', (prep/'train_requests.jsonl').read_text())
            a=argparse.Namespace(data_dir=str(data),prepared_dir=str(prep),output_dir=root+'/run',base_urls=['http://local:8000'],model='social-base',temperature=.7,timeout=5,seed=1,samples=2)
            with mock_http(lambda body,n:response(['neutral'] if n==1 else ['want'])) as sent:
                result=probe(a)
            self.assertEqual(result['totals']['groups_with_valid_task_variation'],1)
            self.assertEqual([r['top_p'] for r in sent],[1,1])
            self.assertEqual([r['top_k'] for r in sent],[-1,-1])
            self.assertNotEqual(sent[0]['seed'],sent[1]['seed'])
            self.assertEqual(sent[0]['messages'],sent[1]['messages'])
            self.assertNotIn('SECRET_GOLD',json.dumps(sent))

    def test_protocol_variation_not_task_variation_and_retry_excluded(self):
        t=task('a',[],['neutral'])
        from training.b_sft.social_b_evaluation import score_attempt
        cs=[]
        for attempt,c in [(0,completion(['want'])),(0,dict(message=dict(content='bad'))),(1,completion(['neutral']))]:
            cs.append(dict(c,checkpoint='a',attempt=attempt,score=score_attempt(t,c)))
        result=analyze(cs,{'a':t},[dict(id='a',category='update',family='a')],2)
        g=result['groups'][0]
        self.assertTrue(g['reward_varies']);self.assertFalse(g['valid_task_reward_varies'])
        self.assertEqual(g['positive_samples'],0)
        cs.append(dict(status='infrastructure_failure',checkpoint='a',attempt=0,score=score_attempt(t,dict(status='infrastructure_failure'))))
        g=analyze(cs,{'a':t},[dict(id='a')],3)['groups'][0]
        self.assertFalse(g['complete']);self.assertIn(None,g['rewards'])

if __name__=='__main__':unittest.main()
