"""Run actual production generation methods with CPU backend doubles."""
import ast
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
import numpy as np
import torch


class Proto:
    @staticmethod
    def from_dict(tensors,non_tensors=None,meta_info=None):
        return NS(batch=tensors,non_tensor_batch=non_tensors,meta_info=meta_info)
    @staticmethod
    def materialize_concat(value):return value


def method(file,cls,name,**namespace):
    parsed=ast.parse((Path(__file__).parent/file).read_text())
    klass=next(n for n in parsed.body if getattr(n,'name',None)==cls)
    node=next(n for n in klass.body if getattr(n,'name',None)==name)
    node.decorator_list=[]
    scope=dict(torch=torch,np=np,DataProto=Proto,object_array=lambda xs:np.array(xs,dtype=object),**namespace)
    exec(compile(ast.Module(body=[node],type_ignores=[]),file,'exec'),scope)
    return scope[name]


class NativeLimitTests(unittest.TestCase):
    def test_worker_forwards_limits_and_accepts_over_1024_tokens(self):
        observed=[]
        def generate(prompts,sampling_params,**kwargs):
            observed.extend(p.max_tokens for p in sampling_params)
            return [NS(prompt_token_ids=p['prompt_token_ids'],outputs=[NS(token_ids=[7]*n,
                logprobs=[{7:NS(logprob=-.5)}]*n,finish_reason='stop')])
                for p,n in zip(prompts,(1025,2))]
        worker=NS(worker_config=NS(strategy_args=NS(strategy_name='vllm')),
            strategy=NS(model=NS(generate=generate)),tokenizer=NS(eos_token_id=99,decode=lambda *a,**k:'text'))
        run=method('workers.py','SocialWorker','generate_native',state_offload_manger=lambda *a,**k:nullcontext())
        reqs=[dict(prompt_ids=[1,2],seed=42,max_tokens=4096),dict(prompt_ids=[3],seed=43)]
        data=Proto.from_dict({},np.array([]))
        data.non_tensor_batch={'requests':np.array(reqs,dtype=object)}
        with patch.dict('sys.modules',vllm=NS(SamplingParams=lambda **k:NS(**k))):result=run(worker,data)
        self.assertEqual(observed,[4096,1024])
        self.assertEqual([len(r['response_ids']) for r in result.non_tensor_batch['records']],[1025,2])
        self.assertEqual(len(result.non_tensor_batch['records'][0]['behavior_log_probs']),1025)

    def test_pipeline_forwards_budget_through_padding_and_restores_order(self):
        observed=[]
        def generate(data,blocking):
            requests=data.non_tensor_batch['requests'].tolist();observed.extend(requests)
            return Proto.from_dict({},dict(records=np.array([dict(text=str(r['seed']),finish_reason='stop') for r in requests],dtype=object)))
        pipeline=NS(tokenizer=NS(apply_chat_template=lambda messages,**k:dict(input_ids=messages)),parser=None,
            pipeline_config=NS(sequence_length=16384,actor_infer=NS(world_size=2)),
            actor_infer=NS(generate_native=generate))
        run=method('pipeline.py','SocialPipeline','generate')
        requests=[dict(messages=[1]*(i+1),tools=[],seed=i,**({'max_tokens':4096} if i!=1 else {})) for i in range(3)]
        with patch.dict('sys.modules',{'training.b_sft.social_b_grpo':NS(parse_completion=lambda *a,**k:{})}):
            result=run(pipeline,requests)
            self.assertEqual([r['text'] for r in result],['0','1','2'])
            self.assertEqual(len(observed),4)
            self.assertEqual({r['seed']:r['max_tokens'] for r in observed},{0:4096,1:1024,2:4096,3:4096})
            with self.assertRaisesRegex(ValueError,'refusing truncation'):
                run(pipeline,[dict(messages=[1]*12289,tools=[],seed=0,max_tokens=4096)])


if __name__=='__main__':unittest.main()
