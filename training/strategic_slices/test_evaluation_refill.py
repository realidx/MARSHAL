"""Evaluation equivalence, cross-parent/mode refill and final-test cancellation."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest

from .evaluation_refill import execute
from .terminal_training import mock_generate
from .terminal_training_evaluate import Validator
from .terminal_training_final_test import run_final_test


class EvalStream:
    def __init__(self,generate,concurrency,reverse=False):
        self.generate=generate;self.limit=concurrency;self.reverse=reverse
        self.pending={};self.time=0;self.submitted=[];self.completed=[];self.requests=[];self.closed=False;self.peak=0
    def __enter__(self):return self
    def submit(self,key,req):
        assert len(self.pending)<self.limit and key not in self.pending
        delay=1000 if key.endswith(':0:d0') else 1+req['seed']%3
        self.pending[key]=(self.time+delay,req);self.submitted.append((key,self.time));self.requests.append(req)
        self.peak=max(self.peak,len(self.pending))
    def poll(self):
        self.time=min(t for t,_ in self.pending.values())
        keys=sorted((k for k,(t,_) in self.pending.items() if t==self.time),reverse=self.reverse)
        key=keys[0];_,req=self.pending.pop(key);self.completed.append((key,self.time))
        return [(key,self.generate([req])[0])]
    def __exit__(self,*args):self.closed=True;self.pending.clear()


class EvaluationRefillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from .test_terminal_d import TerminalDTests
        TerminalDTests.setUpClass();cls.tree=TerminalDTests.tree
        cls.cfg=dict(TerminalDTests.cfg,max_tokens=1024,workers=8)
        raw=json.loads((Path(__file__).resolve().parents[2]/'examples/strategic_slices/fixtures/public_history_information.json').read_text())['raw']
        parents={};split_rows={}
        originals=[next(r for r in TerminalDTests.rows if r['k']==k) for k in (1,2,3)]
        for split in ('validation','test'):
            rows=[]
            for p in range(4):
                pid=f'{split}-p{p}'
                parents[pid]=dict(id=pid,family='fixture',players=3,raw=raw,split=split)
                for i,row in enumerate(originals):rows.append(dict(deepcopy(row),id=f'{pid}-{i}',parent_id=pid,split=split))
            split_rows[split]=rows
        cls.data=NS(sha='fixture',parents=parents,reference=lambda _:(cls.tree,{}),**split_rows)
    def factory(self,generate=mock_generate,reverse=False):
        streams=[]
        def factory(n):s=EvalStream(generate,n,reverse);streams.append(s);return s
        return factory,streams
    def test_same_report_for_both_splits_repeats_and_completion_orders(self):
        for split in ('validation','test'):
            old=Validator(self.data,mock_generate,self.cfg,repeats=2,split=split).run()
            for reverse in (False,True):
                factory,streams=self.factory(reverse=reverse)
                evaluator=Validator(self.data,mock_generate,self.cfg,repeats=2,split=split,stream_factory=factory)
                report=evaluator.run();self.assertEqual(report,old)
                self.assertEqual(len(streams),2)
                self.assertEqual(report['generated_response_tokens'],2*sum(len(s.completed) for s in streams))
                for s in streams:
                    self.assertTrue(s.closed);self.assertEqual(len(s.submitted),len(s.completed));self.assertLessEqual(s.peak,8)
                    self.assertTrue(all(r['temperature']==0. and r['max_tokens']==1024 for r in s.requests))
                self.assertEqual(evaluator.last_execution['slices']['jobs'],24)
                self.assertEqual(evaluator.last_execution['full_games']['jobs'],32)
    def test_cross_parent_and_mode_work_starts_before_straggler(self):
        factory,streams=self.factory()
        Validator(self.data,mock_generate,self.cfg,repeats=2,split='test',stream_factory=factory).run()
        slices,full=streams
        # Eight active jobs span multiple parents. More jobs start while fixed
        # cohort index zero is still generating its first answer.
        self.assertTrue(any(int(k.split(':')[-2])>=8 and t<1000 for k,t in slices.submitted))
        # Eight team episodes precede focal-reference episodes in the fixed
        # report order; now they share the actual generation pool.
        self.assertTrue(any(int(k.split(':')[-2])>=8 and t<1000 for k,t in full.submitted))
        self.assertEqual({s.peak for s in streams},{8})
    def test_failures_and_output_budget_are_identical_to_legacy(self):
        def mixed(requests):
            outs=mock_generate(requests)
            for req,out in zip(requests,outs):
                if req['seed']%7==0:out['finish_reason']='length'
                elif req['seed']%11==0:out['completion']['raw_message']={}
            return outs
        cfg=dict(self.cfg,max_tokens=4096)
        old=Validator(self.data,mixed,cfg,repeats=1,split='test',limit=5).run()
        factory,streams=self.factory(mixed)
        new=Validator(self.data,mixed,cfg,repeats=1,split='test',limit=5,stream_factory=factory).run()
        self.assertEqual(old,new)
        self.assertTrue(all(r['max_tokens']==4096 for s in streams for r in s.requests))
    def test_final_test_native_factory_completion_and_idempotence(self):
        from .test_terminal_final_test import FinalTestTests
        FinalTestTests.setUpClass();base=FinalTestTests()
        with tempfile.TemporaryDirectory() as root:
            p=base.pipeline(root);factory,streams=self.factory()
            p.native_stream=factory
            p.generate=lambda _:self.fail('Native final test fell back to synchronous generation')
            run_final_test(p)
            report=json.loads((p.root/'test/report.json').read_text());done=json.loads((p.root/'test/COMPLETE.json').read_text())
            self.assertEqual(done['identity']['evaluation_scheduler'],'evaluation-completion-refill-v1')
            self.assertEqual(report['slices']['episodes'],4)
            self.assertEqual(report['execution']['slices']['jobs'],4)
            self.assertFalse(report['used_for_checkpoint_selection'])
            before=len(streams);run_final_test(p);self.assertEqual(len(streams),before)
    def test_native_test_interruption_aborts_without_completion_marker_and_can_retry(self):
        from .test_terminal_final_test import FinalTestTests
        FinalTestTests.setUpClass();base=FinalTestTests()
        with tempfile.TemporaryDirectory() as root:
            p=base.pipeline(root)
            def interrupt(requests):p.stop_requested=True;return mock_generate(requests)
            factory,streams=self.factory(interrupt);p.native_stream=factory
            run_final_test(p)
            self.assertEqual(json.loads((p.root/'RESULT.json').read_text())['final_test']['status'],'interrupted')
            self.assertFalse((p.root/'test/COMPLETE.json').exists());self.assertTrue(streams[0].closed)
            self.assertTrue((p.root/'checkpoints/checkpoint-2/COMPLETE.json').exists())
            p.stop_requested=False;p.native_stream=self.factory()[0];run_final_test(p)
            self.assertEqual(json.loads((p.root/'RESULT.json').read_text())['final_test']['status'],'complete')
    def test_native_infrastructure_failure_does_not_complete_test(self):
        from .test_terminal_final_test import FinalTestTests
        FinalTestTests.setUpClass();base=FinalTestTests()
        with tempfile.TemporaryDirectory() as root:
            p=base.pipeline(root)
            def broken(_):raise RuntimeError('native evaluation transport failed')
            factory,streams=self.factory(broken);p.native_stream=factory
            with self.assertRaisesRegex(RuntimeError,'transport failed'):run_final_test(p)
            self.assertEqual(json.loads((p.root/'RESULT.json').read_text())['final_test']['status'],'failed')
            self.assertFalse((p.root/'test/COMPLETE.json').exists());self.assertTrue(streams[0].closed)
            self.assertEqual(p.events[-1],'offload_infer')
    def test_lazy_admission_is_bounded_and_duplicate_completion_rejected(self):
        built=[];live=set();peak=[];finished=[];streams=[]
        def make(spec):
            built.append(spec);live.add(spec);peak.append(len(live));return NS(status='running',calls=[],spec=spec)
        def accept(job,out,req):job.calls.append(out);job.status='terminal'
        def complete(index,spec,job):live.remove(spec);finished.append(index)
        def fake_generate(requests):return [{} for _ in requests]
        def factory(n):s=EvalStream(fake_generate,n);streams.append(s);return s
        stats=execute(range(40),make,lambda j:dict(seed=j.spec),accept,complete,factory,4,'fake')
        self.assertEqual(stats['jobs'],40);self.assertEqual(max(peak),4);self.assertEqual(len(set(finished)),40)
        # Fault injection must abort the session rather than counting a response twice.
        class Duplicate(EvalStream):
            def poll(self):out=super().poll();return out+out
        def duplicate(n):s=Duplicate(fake_generate,n);streams.append(s);return s
        with self.assertRaisesRegex(RuntimeError,'duplicate'):
            execute(range(2),make,lambda j:dict(seed=0),accept,complete,duplicate,2,'bad')
        self.assertTrue(streams[-1].closed)

    def test_actual_native_bridge_worker_and_validator_match_synchronous_report(self):
        # Run the production NativeStream and actual worker methods end-to-end;
        # only Ray, tokenizer and GPU engine are replaced by CPU doubles.
        from training.social_mixed.test_native_stream import NativeStreamTests
        helper=NativeStreamTests();helper.setUp();self.addCleanup(helper.doCleanups)
        def zero(requests):
            outs=mock_generate(requests)
            for req,out in zip(requests,outs):
                out['completion']['raw_message']['tool_calls'][0]['function']['arguments']=json.dumps(dict(action_index=0))
                out.update(response_ids=[7,9],behavior_log_probs=[-.4,-.2],text='answer',request=req)
            return outs
        def factory(n):
            stream,workers,_=helper.bridge()
            stream.limits=[n//2+int(i<n%2) for i in range(2)]
            stream.pipeline.tokenizer.apply_chat_template=lambda *a,**k:dict(input_ids=[1,2])
            completion=dict(finish_reason='tool_calls',raw_message=dict(tool_calls=[
                dict(function=dict(name='act',arguments=json.dumps(dict(action_index=0))))]))
            stream.parse=lambda *a,**k:deepcopy(completion)
            for worker in workers:
                original=worker.engine.add_requests
                def add(*args,original=original,worker=worker,**kwargs):
                    original(*args,**kwargs)
                    for value in worker.engine.pending.values():value['remaining']=1
                worker.engine.add_requests=add
            return stream
        expected=Validator(self.data,zero,self.cfg,limit=3).run()
        actual=Validator(self.data,zero,self.cfg,limit=3,stream_factory=factory).run()
        self.assertEqual(actual,expected)


if __name__=='__main__':unittest.main()
