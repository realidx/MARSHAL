import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch

from training.b_sft.run_social_b_eval import checkpoint, run
from training.b_sft.test_social_b_evaluation import task, completion
from methods.vllm_client import OpenAICompatibleNegotiationClient


@contextmanager
def mock_http(responses):
    # Exercise the real client's serialization and response parsing, without
    # opening sockets (also runs inside network-restricted workspaces).
    requests=[]
    class Response:
        def __init__(self,payload): self.payload=payload
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def read(self): return json.dumps(self.payload).encode()
    def urlopen(req,timeout):
        body=json.loads(req.data);requests.append(body)
        result=responses(body,len(requests))
        if isinstance(result,Exception): raise result
        return Response(result)
    with patch('urllib.request.urlopen',urlopen): yield requests


def response(values=['neutral'], tokens=20, reason='stop'):
    return dict(choices=[dict(message=completion(values)['message'],finish_reason=reason)],usage=dict(completion_tokens=tokens))


class RunnerTests(unittest.TestCase):
    def test_native_retry_feedback_and_shared_budget(self):
        def server(body,n):
            if n==1:
                return dict(choices=[dict(message=dict(role='assistant',content='SUBMIT_BELIEFS({})'),finish_reason='stop')],usage=dict(completion_tokens=100))
            return response()
        with mock_http(server) as sent:
            logged=[]
            attempts=checkpoint(task('a',[],['neutral']),OpenAICompatibleNegotiationClient('http://local:8000','social-base'),mode='independent',prior=[],emit=logged.append)
        self.assertEqual([r['score']['status'] for r in logged],['format_failure','ok'])
        self.assertEqual([r['max_tokens'] for r in sent],[1024,924])
        self.assertIn('retry_feedback',sent[1]['messages'][-1]['content'])
        self.assertNotIn('gold',json.dumps(sent))
        self.assertEqual(sent[0]['tool_choice'],'auto')
        self.assertNotIn('chat_template',sent[0])

    def test_exhausted_truncation_and_unknown_usage_never_retry(self):
        for payload,status in [(response(tokens=1024,reason='length'),'truncated'),
                               (dict(response(),usage={}),'infrastructure_failure'),
                               (TimeoutError('timeout'),'infrastructure_failure')]:
            with mock_http(lambda body,n:payload) as sent:
                result=checkpoint(task('a',[],['neutral']),OpenAICompatibleNegotiationClient('http://local','social-base'),mode='independent',prior=[],emit=lambda r:None)
            self.assertEqual(len(sent),1)
            self.assertEqual(result[-1]['score']['status'],status)

    def test_complete_four_endpoint_runner_and_previous_native_messages(self):
        with tempfile.TemporaryDirectory() as root:
            data=Path(root)/'data';data.mkdir()
            tasks=[dict(task(str(i),[{'action':'PASS'} for j in range(i)],['neutral']),split='test',source='fixture') for i in range(3)]
            files={'tasks.jsonl':tasks,'sequences.jsonl':[dict(id='seq',split='test',checkpoints=['0','1','2'])],
                   'pairs.jsonl':[dict(before='0',after='1',query=dict(player=1,goal=0),category='maintain')]}
            for name,rs in files.items(): (data/name).write_text(''.join(json.dumps(r)+'\n' for r in rs))
            args=argparse.Namespace(data_dir=str(data),output_dir=str(Path(root)/'out'),split='all',mode='both',limit=0,
                 base_urls=['http://local:'+str(8000+i) for i in range(4)],model='social-base',temperature=.7,timeout=5)
            with mock_http(lambda body,n:response()) as sent:
                result=run(args)
            self.assertEqual(result['completed_checkpoints'],6)
            self.assertEqual(result['modes']['sequential']['final']['checkpoint_exact_rate'],1)
            continuous=[r for r in sent if any(m['role']=='tool' for m in r['messages'])]
            self.assertEqual(len(continuous),2)
            for r in continuous:
                assistant=next(m for m in r['messages'] if m['role']=='assistant')
                ack=next(m for m in r['messages'] if m['role']=='tool')
                self.assertEqual(assistant['tool_calls'][0]['id'],ack['tool_call_id'])
            with self.assertRaises(FileExistsError):run(args)


if __name__=='__main__': unittest.main()
