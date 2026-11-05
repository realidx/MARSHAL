"""Strict tool-call supervision and dynamic padding (no truncation)."""

import json
import hashlib
from pathlib import Path


def encode_sample(sample, tokenizer, max_length):
    messages = sample['messages']
    if [m['role'] for m in messages] != ['system', 'user', 'assistant']:
        raise ValueError('Expected exactly system/user/assistant messages')
    target = messages[-1]
    calls = target.get('tool_calls', [])
    if target.get('content') or len(calls) != 1:
        raise ValueError('Only one assistant tool call, without reasoning targets, is supported')
    function = calls[0]['function']
    if function['name'] != 'SUBMIT_JUDGMENT':
        raise ValueError('Unexpected supervision tool')
    arguments = function['arguments']
    if isinstance(arguments, str):
        arguments = json.loads(arguments)
    values = arguments.get('possible_preferences')
    if (set(arguments) != {'possible_preferences'} or not isinstance(values, list)
            or not values or any(v not in ('want', 'neutral', 'avoid') for v in values)
            or len(values) != len(set(values))):
        raise ValueError('Invalid semantic target set')
    options = dict(tools=sample['tools'], tokenize=False)
    prompt = tokenizer.apply_chat_template(messages[:-1], add_generation_prompt=True, **options)
    full = tokenizer.apply_chat_template(messages, add_generation_prompt=False, **options)
    if not full.startswith(prompt):
        raise ValueError('Chat template does not preserve the generation prefix')
    completion = full[len(prompt):]
    try:
        rendered_call = json.loads(completion.split('<tool_call>', 1)[1].split('</tool_call>', 1)[0])
    except (ValueError, IndexError) as error:
        raise ValueError('Template did not render a native Qwen tool call') from error
    if rendered_call != {'name': function['name'], 'arguments': arguments}:
        raise ValueError('Template changed the supervised tool arguments')
    prompt_ids = tokenizer(prompt, add_special_tokens=False)['input_ids']
    ids = tokenizer(full, add_special_tokens=False)['input_ids']
    if ids[:len(prompt_ids)] != prompt_ids or len(ids) <= len(prompt_ids):
        raise ValueError('Assistant token boundary is not aligned')
    if len(ids) > max_length:
        raise ValueError(f"Sample {sample.get('id')} has {len(ids)} tokens; limit {max_length}; refusing truncation")
    return dict(input_ids=ids, attention_mask=[1] * len(ids),
                labels=[-100] * len(prompt_ids) + ids[len(prompt_ids):])


def load_records(path):
    check_corpus_export(path)
    rows = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    if not rows:
        raise ValueError(f'Empty dataset: {path}')
    ids = [r['id'] for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError(f'Duplicate sample IDs: {path}')
    return rows


def check_corpus_export(path):
    """New corpus exports are usable only after their final atomic ready marker."""
    path = Path(path)
    manifest = path.parent / 'manifest.json'
    if not manifest.exists() or not str(json.loads(manifest.read_text()).get('version', '')).startswith('b-corpus-'):
        return  # Existing verified roles-v1 exports retain their original contract.
    ready = path.parent / 'READY.json'
    checksums = path.parent / 'checksums.json'
    if not ready.exists() or not checksums.exists():
        raise ValueError('Corpus export is incomplete: READY.json/checksums.json required')
    marker = json.loads(ready.read_text())
    if marker.get('complete') is not True or marker.get('checksums_sha256') != hashlib.sha256(checksums.read_bytes()).hexdigest():
        raise ValueError('Corpus ready/checksum manifest mismatch')
    expected = json.loads(checksums.read_text()).get(path.name)
    if expected != hashlib.sha256(path.read_bytes()).hexdigest():
        raise ValueError(f'Corpus file checksum mismatch: {path.name}')


def check_split(train, evaluation):
    if {r['id'] for r in train} & {r['id'] for r in evaluation}:
        raise ValueError('Train/evaluation sample overlap')
    if {r['source_id'] for r in train} & {r['source_id'] for r in evaluation}:
        raise ValueError('Train/evaluation source overlap')


def check_resume(checkpoint, signature):
    manifests = sorted(Path(checkpoint).parent.glob('run_manifest_*.json'))
    if not manifests:
        raise ValueError('Resume requires the original run manifest alongside checkpoint directories')
    previous = json.loads(manifests[-1].read_text()).get('resume_signature')
    if previous != signature:
        raise ValueError('Resume model/data/template/config differs from the original run; start a fresh run')


def pad_features(features, pad_token_id):
    width = max(len(f['input_ids']) for f in features)
    return {key: [f[key] + [pad] * (width - len(f[key])) for f in features]
            for key, pad in [('input_ids', pad_token_id), ('attention_mask', 0), ('labels', -100)]}


class ToolCollator:
    def __init__(self, pad_token_id):
        self.pad_token_id = pad_token_id

    def __call__(self, features):
        import torch
        return {k: torch.tensor(v, dtype=torch.long)
                for k, v in pad_features(features, self.pad_token_id).items()}
