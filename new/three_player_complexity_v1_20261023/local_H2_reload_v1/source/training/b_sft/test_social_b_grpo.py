import ast
import json
from pathlib import Path
import unittest
from training.b_sft.social_presentation import commitment_ids

class NativeTrainingTests(unittest.TestCase):
    def test_rlvr_encoder_preserves_tools_and_no_duplicate_special_tokens(self):
        # Execute the actual lightweight encoder without importing Ray/GPU deps.
        source=Path('roll/pipeline/rlvr/rlvr_pipeline.py').read_text()
        fn=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='get_encode_function')
        seen=[]
        def get_template(name,tok):
            def render(messages,tools=None):
                seen.append((messages,tools));return 'native prompt'
            return render
        class Tokenizer:
            def __call__(self,texts,**kw):return {'texts':texts,'kwargs':kw}
        scope=dict(json=json,get_chat_template=get_template)
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'<encoder>','exec'),scope)
        tools=[{'type':'function','function':{'name':'SUBMIT_BELIEFS'}}]
        messages=[{'role':'user','content':'Visible facts'}]
        result=scope['get_encode_function']('native',Tokenizer())(dict(messages=[json.dumps(messages)],tools=[json.dumps(tools)]))
        self.assertEqual(seen,[(messages,tools)])
        self.assertFalse(result['kwargs']['add_special_tokens'])

    def test_dedicated_vllm_cards_skip_sleep_allocator(self):
        from types import SimpleNamespace
        source=Path('roll/third_party/vllm/worker_helper.py').read_text()
        cls=next(n for n in ast.parse(source).body if isinstance(n,ast.ClassDef))
        fn=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='offload_states')
        scope={}
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'<offload>','exec'),scope)
        def fail(*args): raise AssertionError('Resident mode must not enter sleep allocator')
        worker=SimpleNamespace(model_config=SimpleNamespace(enable_sleep_mode=False),
                               weight_loaded=True,kv_cache_loaded=True,sleep=fail)
        scope['offload_states'](worker,1)
        self.assertTrue(worker.weight_loaded)
        self.assertTrue(worker.kv_cache_loaded)

    def test_vllm_callback_preserves_actual_tokens_and_sample_order(self):
        from types import SimpleNamespace
        source=Path('roll/distributed/strategy/vllm_strategy.py').read_text()
        cls=next(n for n in ast.parse(source).body if isinstance(n,ast.ClassDef))
        fn=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='process_vllm_output')
        for arg in fn.args.args: arg.annotation=None
        scope={'DataProto':lambda **kwargs:SimpleNamespace(**kwargs)}
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'<vllm callback>','exec'),scope)
        ids=[[70,71,99],[72,99]]
        worker=SimpleNamespace(request_metas={'actual':{'request_id':'actual','index':3}})
        outputs=[SimpleNamespace(request_id='actual',outputs=[SimpleNamespace(token_ids=row) for row in ids]),
                 SimpleNamespace(request_id='cancelled',outputs=[])]
        results=[]
        scope['process_vllm_output'](worker,outputs,lambda data:results.append(data))
        self.assertEqual(len(results),1)
        self.assertEqual(results[0].meta_info['output_token_ids'],ids)
        self.assertEqual(results[0].meta_info['index'],3)

if __name__=='__main__':unittest.main()
