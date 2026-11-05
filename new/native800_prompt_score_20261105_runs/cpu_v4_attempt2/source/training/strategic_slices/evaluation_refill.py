"""Bounded, lazy closed-loop evaluation; completions never select the cohort."""
from collections import deque
import time

VERSION='evaluation-completion-refill-v1'


def execute(specs,make_job,request,accept,complete,stream_factory,concurrency,scope,stop_check=None):
    if type(concurrency) is not int or concurrency<1:raise ValueError('Positive evaluation concurrency required')
    source=iter(enumerate(specs));active={};ready=deque();pending={};exhausted=False
    admitted=finished=calls=tokens=peak=0;started=time.perf_counter()
    def check():
        if stop_check is not None:stop_check()
    check()
    with stream_factory(concurrency) as stream:
        while not exhausted or active:
            check()
            while not exhausted and len(active)<concurrency:
                check()
                try:index,spec=next(source)
                except StopIteration:exhausted=True;break
                job=make_job(spec);admitted+=1
                if job.status!='running':complete(index,spec,job);finished+=1
                else:active[index]=(spec,job);ready.append(index)
            while ready and len(pending)<concurrency:
                check();index=ready.popleft();_,job=active[index]
                req=request(job);key=f'eval:{scope}:{index}:d{len(job.calls)}'
                stream.submit(key,req);pending[key]=(index,req);peak=max(peak,len(pending))
            if not pending:
                if active:raise RuntimeError('Evaluation has active jobs but no pending requests')
                continue
            events=stream.poll();check()
            for key,out in events:
                if key not in pending:raise RuntimeError('Unknown/duplicate evaluation completion')
                index,req=pending.pop(key);spec,job=active[index]
                accept(job,out,req);calls+=1;tokens+=len(out.get('response_ids',[]))
                if job.status=='running':ready.append(index)
                else:
                    complete(index,spec,job);finished+=1;del active[index]
        if pending or ready or finished!=admitted:raise RuntimeError('Evaluation did not drain its complete cohort')
    return dict(version=VERSION,jobs=finished,decision_calls=calls,generated_response_tokens=tokens,
        peak_inflight=peak,seconds=time.perf_counter()-started,native_ticks=getattr(stream,'ticks',0),
        prompt_tokenizations=getattr(stream,'tokenizations',0))
