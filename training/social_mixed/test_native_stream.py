"""Execute production stream RPCs and bridge with CPU engine/Ray doubles."""
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from .native_stream import NativeStream
from .test_native_limits import method


class Engine:
    def __init__(self):self.pending={};self.added=[];self.aborted=[];self.steps=0
    def add_requests(self,prompt_token_ids,request_ids,sampling_params,multi_modal_data):
        for key,ids in zip(request_ids,prompt_token_ids):
            self.pending[key]=dict(ids=ids,remaining=int(sampling_params.seed),limit=sampling_params.max_tokens)
            self.added.append((key,sampling_params))
    def fetch_output(self):
        self.steps+=1;done=[]
        for key,r in list(self.pending.items()):
            r['remaining']-=1
            if r['remaining']<=0:
                done.append(NS(request_id=key,prompt_token_ids=r['ids'],finished=True,
                    outputs=[NS(token_ids=[7,9],logprobs=[{7:NS(logprob=-.4)},{9:NS(logprob=-.2)}],finish_reason='stop')]))
                del self.pending[key]
        return done
    def abort_request(self,keys):
        self.aborted.extend(keys)
        for key in keys:self.pending.pop(key,None)
    def clear_unfinished_requests(self):self.pending.clear()


class Ref:
    def __init__(self,result,rank):self.result,self.rank=result,rank


class FakeRay:
    def __init__(self):self.waited=[]
    def wait(self,refs,num_returns):
        self.waited.append(num_returns)
        # Make the second worker fast. A wait-all bridge would incorrectly
        # hold its finished output behind worker zero's long request.
        ready=min(refs,key=lambda r:(not bool(r.result.get('records')), -r.rank))
        return [ready],[r for r in refs if r is not ready]
    def get(self,refs):return [self.get(r) for r in refs] if isinstance(refs,list) else refs.result


class NativeStreamTests(unittest.TestCase):
    def setUp(self):
        self.tick=method('workers.py','SocialWorker','native_stream_tick')
        self.close=method('workers.py','SocialWorker','native_stream_close')
        self.vllm=patch.dict('sys.modules',vllm=NS(SamplingParams=lambda **kwargs:NS(**kwargs)))
        self.vllm.start();self.addCleanup(self.vllm.stop)
    def worker(self):
        engine=Engine();loads=[]
        w=NS(worker_config=NS(strategy_args=NS(strategy_name='vllm')),strategy=NS(model=engine,load_states=lambda:loads.append(1)),
            tokenizer=NS(eos_token_id=9,decode=lambda *a,**k:'answer'),engine=engine,loads=loads)
        return w
    def payload(self,requests,max_steps=16):return dict(session='fixed',requests=requests,capacity=2,max_steps=max_steps)
    def request(self,key,seed):return dict(request_id=key,prompt_ids=[1,2],seed=seed,max_tokens=1024,temperature=1.)
    def test_tick_returns_short_before_long_and_accepts_refill_with_native_evidence(self):
        w=self.worker()
        first=self.tick(w,self.payload([self.request('long',100),self.request('short',1)]))
        self.assertEqual([r['request_id'] for r in first['records']],['short']);self.assertEqual(first['pending'],1)
        second=self.tick(w,self.payload([self.request('refill',2)]))
        self.assertEqual([r['request_id'] for r in second['records']],['refill']);self.assertEqual(second['pending'],1)
        self.assertEqual(w.loads,[1]);self.assertLess(w.engine.steps,100)
        r=second['records'][0]
        self.assertEqual(r['response_ids'],[7,9]);self.assertEqual(r['behavior_log_probs'],[-.4,-.2])
        self.assertEqual([p.seed for _,p in w.engine.added],[100,1,2])
        self.assertTrue(all(p.logprobs==0 and p.temperature==1. and p.top_p==1. for _,p in w.engine.added))
        self.close(w,'fixed');self.assertEqual(w.engine.aborted,['long']);self.assertIsNone(w._native_stream_state)
    def test_tick_yields_without_waiting_for_long_answer_and_close_cleans_it(self):
        w=self.worker();r=self.tick(w,self.payload([self.request('long',1000)],max_steps=16))
        self.assertEqual(r,dict(records=[],pending=1));self.assertEqual(w.engine.steps,16)
        with self.assertRaisesRegex(RuntimeError,'still active'):
            self.tick(w,dict(self.payload([]),session='wrong'))
        self.close(w,'fixed');self.assertFalse(w.engine.pending)
    def test_capacity_and_invalid_behavior_evidence_fail(self):
        w=self.worker();self.tick(w,self.payload([self.request('a',100),self.request('b',100)]))
        with self.assertRaisesRegex(ValueError,'capacity'):self.tick(w,self.payload([self.request('c',1)]))
        self.close(w,'fixed')
        w=self.worker();original=w.engine.fetch_output
        def broken():
            out=original()
            for r in out:r.outputs[0].logprobs=None
            return out
        w.engine.fetch_output=broken
        with self.assertRaisesRegex(RuntimeError,'token log probabilities'):
            self.tick(w,self.payload([self.request('broken',1)]))
        self.close(w,'fixed');self.assertIsNone(w._native_stream_state)
    def bridge(self):
        ray=FakeRay();workers=[self.worker(),self.worker()]
        endpoints=[]
        for rank,w in enumerate(workers):
            endpoints.append(NS(native_stream_tick=NS(remote=lambda p,w=w,rank=rank:Ref(self.tick(w,p),rank)),
                native_stream_close=NS(remote=lambda s,w=w,rank=rank:Ref(self.close(w,s),rank))))
        p=NS(tokenizer=NS(apply_chat_template=lambda messages,**k:dict(input_ids=messages)),
            parser=None,pipeline_config=NS(sequence_length=16384),actor_infer=NS(workers=endpoints))
        with patch.dict('sys.modules',ray=ray,**{'training.b_sft.social_b_grpo':NS(parse_completion=lambda *a,**k:dict(ok=True))}):
            stream=NativeStream(p,2)
        return stream,workers,ray
    def test_bridge_polls_any_worker_and_refills_without_dummy_samples(self):
        stream,workers,ray=self.bridge()
        def req(seed):return dict(messages=[1,2],tools=[],seed=seed,max_tokens=1024)
        with stream:
            stream.submit('long',req(100));stream.submit('short',req(1))
            event=stream.poll();self.assertEqual([k for k,_ in event],['short'])
            stream.submit('refill',req(1))
            event=stream.poll();self.assertEqual([k for k,_ in event],['refill'])
            while stream.requests:stream.poll()
        self.assertTrue(all(n==1 for n in ray.waited));self.assertEqual(stream.peak,2)
        self.assertEqual(sum(len(w.engine.added) for w in workers),3)
        self.assertTrue(all(w._native_stream_state is None for w in workers))
    def test_bridge_failure_aborts_and_flushes_pending_before_exit(self):
        stream,workers,ray=self.bridge()
        with self.assertRaisesRegex(RuntimeError,'collection failed'):
            with stream:
                stream.submit('long',dict(messages=[1],tools=[],seed=100,max_tokens=1024));stream.poll()
                raise RuntimeError('collection failed')
        self.assertEqual(workers[0].engine.aborted,['long']);self.assertTrue(all(getattr(w,'_native_stream_state',None) is None for w in workers))
    def test_prompt_encoded_once_with_independent_seeds_and_limit_checks(self):
        stream,workers,ray=self.bridge();encoded=[]
        def tokenizer(messages,**kwargs):encoded.append((messages,kwargs['tools']));return dict(input_ids=[1,2])
        stream.pipeline.tokenizer.apply_chat_template=tokenizer
        with stream:
            for i in range(8):
                stream.submit(str(i),dict(messages=[dict(content='same')],tools=[],seed=i+1,max_tokens=1024))
                while stream.requests:stream.poll()
            self.assertEqual(stream.tokenizations,1);self.assertEqual(len(encoded),1)
            self.assertEqual(stream.prompt_cache.hits,7)
            # A cached prompt still checks each request's output/context budget.
            with self.assertRaisesRegex(ValueError,'refusing truncation'):
                stream.submit('too-long',dict(messages=[dict(content='same')],tools=[],seed=1,max_tokens=16383))
            stream.submit('changed',dict(messages=[dict(content='different')],tools=[],seed=1,max_tokens=1024))
            while stream.requests:stream.poll()
            self.assertEqual(stream.tokenizations,2)
        seeds=[p.seed for w in workers for _,p in w.engine.added]
        self.assertEqual(sorted(seeds),[1,1,2,3,4,5,6,7,8])


if __name__=='__main__':unittest.main()
