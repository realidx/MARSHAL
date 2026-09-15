import json
from pathlib import Path

import pytest

from training.b_sft.data import check_resume, check_split, encode_sample, load_records, pad_features
from training.b_sft.summarize import summarize


class Tokenizer:
    def apply_chat_template(self, messages, **kwargs):
        prompt = '<system>rules<user>history<assistant>'
        if kwargs['add_generation_prompt']:
            return prompt
        call = messages[-1]['tool_calls'][0]['function'].copy()
        call['arguments'] = json.loads(call['arguments'])
        return prompt + '<tool_call>' + json.dumps(call) + '</tool_call><eos>'

    def __call__(self, text, **kwargs):
        return {'input_ids': [ord(c) for c in text]}


def sample():
    return {'id': 'a', 'source_id': 's1', 'tools': [], 'messages': [
        {'role': 'system', 'content': 'rules'}, {'role': 'user', 'content': 'history'},
        {'role': 'assistant', 'content': '', 'tool_calls': [{'function': {
            'name': 'SUBMIT_JUDGMENT', 'arguments': '{"possible_preferences":["want","neutral"]}'}}]}]}


def test_only_completion_supervised_and_padding_masked():
    encoded = encode_sample(sample(), Tokenizer(), 4096)
    start = len('<system>rules<user>history<assistant>')
    assert encoded['labels'][:start] == [-100] * start
    assert encoded['labels'][start:] == encoded['input_ids'][start:]
    short = {'input_ids': [1, 2], 'attention_mask': [1, 1], 'labels': [-100, 2]}
    batch = pad_features([encoded, short], 0)
    assert batch['labels'][1][2:] == [-100] * (len(encoded['input_ids']) - 2)
    assert sum(batch['attention_mask'][1]) == 2


def test_overlength_rejected():
    with pytest.raises(ValueError, match='refusing truncation'):
        encode_sample(sample(), Tokenizer(), 10)


def test_bad_token_boundary_rejected():
    class Broken(Tokenizer):
        def __call__(self, text, **kwargs):
            ids = super().__call__(text, **kwargs)['input_ids']
            return {'input_ids': ids if '<tool_call>' not in text else [999] + ids}
    with pytest.raises(ValueError, match='boundary'):
        encode_sample(sample(), Broken(), 4096)


@pytest.mark.parametrize('values', [[], ['want', 'want'], ['unknown']])
def test_invalid_gold_rejected(values):
    row = sample()
    row['messages'][-1]['tool_calls'][0]['function']['arguments'] = json.dumps({'possible_preferences': values})
    with pytest.raises(ValueError, match='semantic'):
        encode_sample(row, Tokenizer(), 4096)


def test_source_overlap_and_duplicates_rejected(tmp_path):
    with pytest.raises(ValueError, match='source overlap'):
        check_split([sample()], [{'id': 'b', 'source_id': 's1'}])
    path = tmp_path / 'data.jsonl'
    path.write_text((json.dumps(sample()) + '\n') * 2)
    with pytest.raises(ValueError, match='Duplicate'):
        load_records(path)


def test_resume_timing_uses_latest_record_and_slowest_rank(tmp_path):
    (tmp_path / 'run_manifest_1.json').write_text(json.dumps(
        {'world_size': 2, 'arguments': {'gradient_accumulation': 2}}))
    for rank in range(2):
        rows = [dict(rank=rank, step=step, step_seconds=rank+1, reserved_peak_bytes=2**30)
                for step in [1, 2, 3]]
        if rank == 1:
            rows.append(dict(rank=rank, step=3, step_seconds=4, reserved_peak_bytes=2**30))
        (tmp_path / f'rank_{rank}_steps.jsonl').write_text('\n'.join(json.dumps(r) for r in rows))
    result = summarize(tmp_path, warmup=1)
    assert result['mean_step_seconds'] == 3
    assert result['nominal_samples_per_second'] == pytest.approx(4/3)


def test_configs_only_differ_in_offload():
    root = Path(__file__).parent / 'configs'
    base = json.loads((root / 'zero3_shared.json').read_text())
    offload = json.loads((root / 'zero3_shared_optimizer_offload.json').read_text())
    assert offload['zero_optimization'].pop('offload_optimizer') == {'device': 'cpu', 'pin_memory': True}
    assert base == offload
    assert base['zero_optimization']['stage3_gather_16bit_weights_on_model_save'] is False


def test_resume_rejects_changed_data_or_strategy(tmp_path):
    signature = {'data': 'abc', 'strategy': 'zero3'}
    (tmp_path / 'run_manifest_1.json').write_text(json.dumps({'resume_signature': signature}))
    check_resume(tmp_path / 'checkpoint-20', signature)
    with pytest.raises(ValueError, match='differs'):
        check_resume(tmp_path / 'checkpoint-20', {'data': 'changed', 'strategy': 'zero3'})
