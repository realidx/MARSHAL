"""Native-tool B/P exports for ROLL. Teacher fields never enter model messages."""
import argparse
import hashlib
import json
from pathlib import Path

from training.b_sft import social_named_probe as named
from training.b_sft.social_bp_training import VERSION, CONTRACT, reward, native_completion, select_batch
from training.b_sft.social_b_grpo import parse_completion


def read(path):
    return [json.loads(s) for s in Path(path).read_text().splitlines() if s.strip()]


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_tasks(tasks):
    from training.b_sft.bp_semantics import semantic_id
    families = {}; seen = set(); prompt_keys = set(); semantics = set()
    development = json.loads((Path(__file__).resolve().parents[2]/'examples/social_bp/development_families.json').read_text())['families']
    for t in tasks:
        if not t.get('training_ready') or t['mechanism'] != VERSION: raise ValueError('Unaudited/stale task')
        if t['id'] in seen: raise ValueError('Duplicate checkpoint')
        seen.add(t['id'])
        semantic = semantic_id(t)
        if semantic != t.get('semantic_id') or semantic in semantics:
            raise ValueError('Stale or duplicate semantic checkpoint')
        semantics.add(semantic)
        if families.setdefault(t['family'], t['split']) != t['split']: raise ValueError('Game family crosses splits')
        if t['split'] != 'train' and t['family'] in development: raise ValueError('Development-probe family in held-out evaluation')
        request = named.request(t, 'action_tools', t.get('name_variant', 0))
        visible = json.dumps(request, sort_keys=True)
        for key in ('type_catalogues', 'policy_sha256', 'action_values', 'proposer_action', 'per_world_payoffs'):
            if key in visible: raise ValueError('Hidden teacher data in visible request: '+key)
        if visible in prompt_keys: raise ValueError('Duplicate visible problem counted as another task')
        prompt_keys.add(visible)
        if reward(t, native_completion(t))['reward'] != 1: raise ValueError('Teacher cannot submit a correct native answer')
    train = [t for t in tasks if t['split'] == 'train']
    for step in range(100):
        for allowed in (0, 2):
            selected = select_batch(train, step, 100, 16, 20260914, dict(allowed={'B': allowed, 'P': allowed}))
            assert len({t['id'] for t in selected}) == 16
            assert sum(t['task'] == 'B' for t in selected) == 8
            assert sum(t.get('direct_answer', False) for t in selected) <= 1
    return dict(tasks=len(tasks), families=len(families), visible_prompts=len(prompt_keys))


def export(data, out, model):
    from transformers import AutoTokenizer
    from vllm.entrypoints.openai.tool_parsers.hermes_tool_parser import Hermes2ProToolParser
    tokenizer = AutoTokenizer.from_pretrained(model, local_files_only=True)
    parser = Hermes2ProToolParser(tokenizer)
    tasks = read(Path(data)/'tasks.jsonl'); checks = validate_tasks(tasks)
    audit = json.loads((Path(data)/'solver_audit.json').read_text())
    if audit['tasks_sha256'] != sha(Path(data)/'tasks.jsonl'):
        raise ValueError('Tasks changed after solver audit')
    template_hash = hashlib.sha256(str(tokenizer.chat_template).encode()).hexdigest()
    if template_hash != audit['summary']['tokenizer']['template_sha256']:
        raise ValueError('Tokenizer template differs from the audited model')
    out = Path(out); out.mkdir(parents=True, exist_ok=False)
    rows = []; lengths = []
    for t in tasks:
        req = named.request(t, 'action_tools', t.get('name_variant', 0))
        text = tokenizer.apply_chat_template(req['messages'], tools=req['tools'], tokenize=False, add_generation_prompt=True)
        ids = tokenizer(text, add_special_tokens=False)['input_ids']
        encoded = tokenizer.apply_chat_template(req['messages'], tools=req['tools'], tokenize=True, add_generation_prompt=True, return_dict=True)
        if ids != encoded['input_ids']: raise ValueError('Template token mismatch')
        if len(ids) > 4096: raise ValueError('Prompt exceeds 4096; no silent truncation')
        lengths.append(len(ids))
        call = native_completion(t)['raw_message']['tool_calls'][0]['function']
        wire = '<tool_call>\n'+json.dumps(dict(name=call['name'], arguments=json.loads(call['arguments'])))+'\n</tool_call>'
        if reward(t, parse_completion(parser, wire, req['tools']))['reward'] != 1:
            raise ValueError('Actual native parser/teacher roundtrip failed')
        if reward(t, parse_completion(parser, json.dumps(call), req['tools']))['reward'] != 0:
            raise ValueError('Ordinary prose must not be accepted as a native tool call')
        teacher = dict(t, tools=req['tools'])
        rows.append(dict(id=t['id'], messages=json.dumps(req['messages']), tools=json.dumps(req['tools']),
                         ground_truth=json.dumps(teacher), tag='social_bp', domain='social_bp'))
    for split in ('train', 'validation', 'test'):
        selected = [r for r, t in zip(rows, tasks) if t['split'] == split]
        (out/(split+'.jsonl')).write_text(''.join(json.dumps(r)+'\n' for r in selected))
    manifest = dict(version=VERSION, contract=CONTRACT, model=model, checks=checks,
        source_tasks_sha256=sha(Path(data)/'tasks.jsonl'), max_prompt_tokens=max(lengths),
        source_audit_sha256=sha(Path(data)/'solver_audit.json'),
        files_sha256={s+'.jsonl': sha(out/(s+'.jsonl')) for s in ('train', 'validation', 'test')},
        template_sha256=template_hash)
    (out/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    return manifest


def validate_export(folder):
    folder = Path(folder); manifest = json.loads((folder/'manifest.json').read_text())
    if manifest['version'] != VERSION or manifest['contract'] != CONTRACT: raise ValueError('Stale export')
    tasks = []
    for split in ('train', 'validation', 'test'):
        path = folder/(split+'.jsonl')
        if sha(path) != manifest['files_sha256'][path.name]: raise ValueError('Export hash mismatch')
        for row in read(path):
            t = json.loads(row['ground_truth']); req = named.request(t, 'action_tools', t.get('name_variant', 0))
            if json.loads(row['messages']) != req['messages'] or json.loads(row['tools']) != req['tools']:
                raise ValueError('Visible training request differs from audited teacher projection')
            if t['split'] != split: raise ValueError('Wrong split')
            tasks.append(t)
    return validate_tasks(tasks)


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--data', required=True); p.add_argument('--out'); p.add_argument('--model'); p.add_argument('--validate-only', action='store_true')
    a = p.parse_args()
    print(json.dumps(validate_tasks(read(Path(a.data)/'tasks.jsonl')) if a.validate_only else export(a.data, a.out, a.model), indent=2))
