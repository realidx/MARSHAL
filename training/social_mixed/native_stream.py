"""Incremental native vLLM evidence and a single-owner driver-side stream.

No HTTP threads, mutable-tokenizer sharing or synthetic padding requests.
"""
import math
from uuid import uuid4

from training.social_mixed.native_limits import output_limit,check_context


def native_record(request,output,tokenizer):
    if list(output.prompt_token_ids)!=request['prompt_ids'] or len(output.outputs)!=1:
        raise RuntimeError('Native generation prompt/replica mismatch')
    sample=output.outputs[0];ids=list(sample.token_ids)
    if sample.finish_reason not in ('stop','length') or not 0<len(ids)<=output_limit(request):
        raise RuntimeError(f'Unscorable native generation: {sample.finish_reason}')
    if sample.logprobs is None or len(sample.logprobs)!=len(ids):
        raise RuntimeError('Missing behavior token log probabilities')
    logps=[float(item[token].logprob) for token,item in zip(ids,sample.logprobs)]
    if not all(math.isfinite(p) for p in logps):raise RuntimeError('Nonfinite behavior log probability')
    return dict(prompt_ids=request['prompt_ids'],response_ids=ids,behavior_log_probs=logps,
        finish_reason=sample.finish_reason,text=tokenizer.decode(ids,skip_special_tokens=False))


class BatchStream:
    """CPU/legacy adapter; the production training path uses NativeStream."""
    def __init__(self,generate,concurrency):self.generate=generate;self.queue=[];self.concurrency=concurrency
    def __enter__(self):return self
    def submit(self,key,request):self.queue.append((key,request))
    def poll(self):
        batch=self.queue;self.queue=[]
        outputs=self.generate([r for _,r in batch])
        if len(outputs)!=len(batch):raise ValueError('Missing native generation output')
        return [(key,out) for (key,_),out in zip(batch,outputs)]
    def __exit__(self,*args):self.queue.clear()


class NativeStream:
    """At most one engine RPC per worker; consume ANY ready worker, then refill."""
    def __init__(self,pipeline,concurrency):
        import ray
        from training.b_sft.social_b_grpo import parse_completion
        self.ray,self.parse=ray,parse_completion
        self.pipeline=pipeline;self.workers=pipeline.actor_infer.workers
        self.session=uuid4().hex;self.refs={};self.requests={};self.peak=0;self.ticks=0
        n=len(self.workers)
        if n<1 or concurrency<1:raise ValueError('Native stream needs workers and positive concurrency')
        self.limits=[concurrency//n+int(i<concurrency%n) for i in range(n)]
        self.pending=[set() for _ in self.workers];self.queued=[[] for _ in self.workers]
    def __enter__(self):return self
    def submit(self,key,request):
        if key in self.requests:raise ValueError('Duplicate streaming request identity')
        available=[i for i in range(len(self.workers)) if len(self.pending[i])<self.limits[i]]
        if not available:raise ValueError('Streaming concurrency exceeded')
        rank=min(available,key=lambda i:(len(self.pending[i]),i))
        p=self.pipeline
        rendered=p.tokenizer.apply_chat_template(request['messages'],tools=request['tools'],tokenize=True,
            add_generation_prompt=True,return_dict=True,truncation=False)
        ids=rendered['input_ids']
        if not isinstance(ids,list) or not ids or any(type(t) is not int for t in ids):
            raise TypeError('Chat template must return one unbatched list of integer input_ids')
        limit=p.pipeline_config.sequence_length
        max_tokens=check_context(len(ids),request,limit)
        encoded=dict(request_id=key,prompt_ids=ids,seed=request['seed'],
            temperature=request.get('temperature',1.),max_tokens=max_tokens)
        self.queued[rank].append(encoded);self.pending[rank].add(key);self.requests[key]=request
        self.peak=max(self.peak,len(self.requests))
    def poll(self):
        busy=set(self.refs.values())
        for rank,worker in enumerate(self.workers):
            if rank not in busy and self.pending[rank]:
                payload=dict(session=self.session,requests=self.queued[rank],capacity=self.limits[rank],max_steps=16)
                self.refs[worker.native_stream_tick.remote(payload)]=rank
                self.queued[rank]=[];self.ticks+=1
        if not self.refs:raise RuntimeError('Streaming poll without pending requests')
        ready,_=self.ray.wait(list(self.refs),num_returns=1)
        events=[]
        for ref in ready:
            rank=self.refs.pop(ref);result=self.ray.get(ref)
            for record in result['records']:
                record=dict(record);key=record.pop('request_id')
                if key not in self.pending[rank]:raise RuntimeError('Unknown/duplicate streaming completion')
                req=self.requests.pop(key);self.pending[rank].remove(key)
                completion=self.parse(self.pipeline.parser,record['text'],req['tools'],truncated=record['finish_reason']=='length')
                events.append((key,dict(record,completion=completion,request=req)))
            expected=len(self.pending[rank])-len(self.queued[rank])
            if result['pending']!=expected:raise RuntimeError('Native engine/driver pending counts differ')
        return events
    def __exit__(self,kind,value,traceback):
        # Actor mailboxes serialize close after any outstanding tick. Abort and
        # flush on failure before the pipeline can sleep or synchronize weights.
        try:
            refs=[w.native_stream_close.remote(self.session) for w in self.workers]
            self.ray.get(refs)
            if kind is None and (self.requests or self.refs):raise RuntimeError('Unfinished native stream')
        except Exception as cleanup:
            if kind is None:raise
            if hasattr(value,'add_note'):value.add_note('Native stream cleanup failed: '+repr(cleanup))
        finally:
            self.refs.clear();self.requests.clear()
