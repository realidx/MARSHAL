"""CPU regression for native rollout metadata and scheduler response splitting.

Execute the production scheduler and DataProto methods without importing the
GPU/Ray runtime. Only TensorDict storage and token padding postprocessing are
stand-ins; NumPy indexing and DataProto's consistency checks are real.
"""
import ast
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
import unittest

import numpy as np
import torch
from torch.nn.utils.rnn import pad_sequence

ROOT = Path(__file__).resolve().parents[2]


class TensorBatch(dict):
    def __init__(self, source, batch_size):
        super().__init__(source)
        self.batch_size = tuple(batch_size)


def load_response_path():
    tree = ast.parse((ROOT / 'roll/distributed/scheduler/protocol.py').read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'DataProto')
    methods = {'__post_init__', '__len__', '__getitem__', 'check_consistency', 'select_idxs', 'repeat'}
    cls.body = [n for n in cls.body if isinstance(n, ast.AnnAssign)
                or isinstance(n, ast.FunctionDef) and n.name in methods]
    scope = dict(np=np, torch=torch, dataclass=dataclass, field=field, Dict=dict, TensorDict=TensorBatch)
    exec(compile(ast.Module(body=[cls], type_ignores=[]), '<DataProto>', 'exec'), scope)
    proto = scope['DataProto']

    def padded_output(prompts, output, num_return_sequences, **kwargs):
        width = prompts.batch['input_ids'].shape[1]
        return proto(batch=TensorBatch({'responses': output[:, width:]}, (num_return_sequences,)))

    scope.update(pad_sequence=pad_sequence, postprocess_generate=padded_output,
                 concatenate_input_and_output=lambda input_ids, output_ids, num_return_sequences:
                 torch.cat((input_ids.repeat(num_return_sequences, 1), output_ids), dim=1))
    tree = ast.parse((ROOT / 'roll/distributed/scheduler/generate_scheduler.py').read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'DynamicSamplingScheduler')
    fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'postprocess_output_ids')
    exec(compile(ast.Module(body=[fn], type_ignores=[]), '<scheduler>', 'exec'), scope)
    return proto, scope['postprocess_output_ids']


class RolloutProtocolTests(unittest.TestCase):
    def test_native_metadata_survives_response_split(self):
        proto, postprocess = load_response_path()
        for count, seed in ((1, None), (1, 20260915), (8, 20260915)):
            with self.subTest(count=count, seed=seed):
                request = proto(batch=TensorBatch({'input_ids': torch.tensor([[1, 2]])}, (1,)),
                                non_tensor_batch={'ground_truth': np.array(['task'], dtype=object)},
                                meta_info={} if seed is None else {'bp_sample_seed': seed})
                scheduler = SimpleNamespace(requests_buffers={'r': request},
                    pipeline_config=SimpleNamespace(social_bp_curriculum=True, sequence_length=8))
                tokens = [[3] if i % 2 == 0 else [4, 5] for i in range(count)]
                reasons = ['stop' if i % 2 == 0 else 'length' for i in range(count)]
                incoming = proto(meta_info=dict(request_id='r', eos_token_id=9, pad_token_id=0,
                                               output_token_ids=tokens, output_finish_reasons=reasons))
                batch = postprocess(scheduler, incoming)
                # Same indexing that failed in report_response after reward union.
                batch.batch['scores'] = torch.ones(count)
                rows = [batch[[idx]] for idx in range(count)]
                for i, row in enumerate(rows):
                    self.assertTrue(all(v.dtype == object for v in row.non_tensor_batch.values()))
                    self.assertEqual(row.non_tensor_batch['ground_truth'].tolist(), ['task'])
                    self.assertEqual(row.non_tensor_batch['bp_token_count'].tolist(), [len(tokens[i])])
                    self.assertEqual(row.non_tensor_batch['bp_finish_reason'].tolist(), [reasons[i]])
                    self.assertEqual(row.batch['responses'][0, :len(tokens[i])].tolist(), tokens[i])
                    if seed is None:
                        self.assertNotIn('bp_sample_seed', row.non_tensor_batch)
                    else:
                        self.assertEqual(int(row.non_tensor_batch['bp_sample_seed'][0]), seed)


if __name__ == '__main__':
    unittest.main()
