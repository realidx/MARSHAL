"""Virtual-time stragglers: refill and unbiased, complete node-group collection."""
from copy import deepcopy
from types import SimpleNamespace as NS
import unittest
import numpy as np

from .terminal_training import Collector,mock_generate
from .common import seed_for


class TimedStream:
    def __init__(self,generate,concurrency,reverse=False):
        self.generate=generate;self.limit=concurrency;self.reverse=reverse
        self.pending={};self.time=0;self.submitted=[];self.completed=[];self.peak=0;self.closed=False
    def __enter__(self):return self
    def submit(self,key,request):
        assert len(self.pending)<self.limit and key not in self.pending
        # Deliberately make the selected root of entrance zero a straggler.
        chosen=int(np.random.default_rng(seed_for(42,'terminal-train-advance',0,0)).integers(8))
        long=key.startswith('node:0:') and key.endswith(f':0:r{chosen}')
        delay=1000 if long else 1+request['seed']%4
        self.pending[key]=(self.time+delay,request);self.submitted.append((key,self.time));self.peak=max(self.peak,len(self.pending))
    def poll(self):
        self.time=min(t for t,_ in self.pending.values())
        keys=sorted((k for k,(t,_) in self.pending.items() if t==self.time),reverse=self.reverse)
        # Deliver exactly one event, including when many requests finish together.
        key=keys[0];_,req=self.pending.pop(key);self.completed.append((key,self.time))
        return [(key,self.generate([req])[0])]
    def __exit__(self,*args):self.closed=True;self.pending.clear()


class RefillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from .test_terminal_training import TrainingTests
        TrainingTests.setUpClass();cls.data=TrainingTests.data
    def run_stream(self,reverse=False):
        streams=[]
        def factory(n):
            s=TimedStream(mock_generate,n,reverse);streams.append(s);return s
        c=Collector(self.data,mock_generate,stream_factory=factory)
        return c,c.collect(0,'slices'),streams[0]
    def test_refills_before_slowest_of_initial_32_and_drains_every_response(self):
        c,result,s=self.run_stream();rows,units,games,m=result
        self.assertTrue(s.closed);self.assertEqual(s.peak,32)
        self.assertTrue(any(k.startswith('node:4:') and t<1000 for k,t in s.submitted))
        self.assertEqual(len(s.submitted),len(s.completed));self.assertEqual(len(rows),8*len(units))
        self.assertTrue(20<=len(units)<=22);self.assertEqual(c.state['cursor'],len(games))
        self.assertEqual(m['generated_tokens'],2*len(rows))
        for u in units:
            calls=[r for r in rows if r['group']==u['group']]
            self.assertEqual(len(calls),8);self.assertEqual(len({r['scoring_sha256'] for r in calls}),1)
    def test_completion_order_does_not_change_samples_rewards_batch_or_resume_state(self):
        a,first,_=self.run_stream();b,second,_=self.run_stream(reverse=True)
        self.assertEqual(first,second);self.assertEqual(a.state,b.state)
        batch=Collector(self.data,mock_generate);self.assertEqual(batch.collect(0,'slices'),first)
        restored=Collector(self.data,mock_generate);restored.restore(a.state)
        self.assertEqual(restored.collect(1,'slices'),a.collect(1,'slices'))
    def test_chosen_response_advances_before_unselected_siblings_finish(self):
        # Use a three-decision entrance; make every NONselected root slow.
        row=next(r for r in self.data.train if r['k']==3)
        data=NS(sha='one',train=[row],reference=self.data.reference)
        selected=int(np.random.default_rng(seed_for(42,'terminal-train-advance',0,0)).integers(8))
        class S(TimedStream):
            def submit(self,key,req):
                super().submit(key,req)
                if key.startswith('node:0:') and ':0:r' in key:
                    self.pending[key]=(1 if key.endswith(f':r{selected}') else 1000,req)
        streams=[]
        def factory(n):s=S(mock_generate,n);streams.append(s);return s
        rows,units,games,_=Collector(data,mock_generate,node_groups_per_update=1,stream_factory=factory).collect(0,'slices')
        # Find an entrance where mock actually continues; this fixture does.
        self.assertGreater(len(units),1)
        self.assertTrue(any(':1:r' in k and t<1000 for k,t in streams[0].submitted))
        self.assertEqual(len(games),1);self.assertEqual(len(rows),8*len(units))
    def test_failed_event_closes_stream_and_does_not_commit_sampler(self):
        streams=[]
        class S(TimedStream):
            def poll(self):
                result=super().poll()
                if len(self.completed)>3:raise RuntimeError('stream transport failure')
                return result
        def factory(n):s=S(mock_generate,n);streams.append(s);return s
        c=Collector(self.data,mock_generate,stream_factory=factory);before=deepcopy(c.state)
        with self.assertRaisesRegex(RuntimeError,'transport'):c.collect(0,'slices')
        self.assertEqual(c.state,before);self.assertTrue(streams[0].closed)


if __name__=='__main__':unittest.main()
