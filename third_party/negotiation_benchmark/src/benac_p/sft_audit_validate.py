"""Validate an exported audit with a pinned, local Qwen tokenizer (no serving).

Requires tokenizers and jinja2. Does not download files, call a model or train.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

from jinja2.sandbox import ImmutableSandboxedEnvironment
from tokenizers import Tokenizer

from benac_p.sft_data_audit import canonical, decode_action, write_json, write_jsonl


def quantiles(values):
    values = sorted(values)
    return dict(min=values[0], median=values[len(values)//2], p95=values[min(len(values)-1, int(len(values)*.95))],
                max=values[-1], total=sum(values), count=len(values))


def validate(output, tokenizer_dir):
    examples = [json.loads(line) for line in (output/'examples.jsonl').read_text().splitlines()]
    labels = {r['id']: r for line in (output/'labels.jsonl').read_text().splitlines() if (r := json.loads(line))}
    games = {g['source_game']: g for p in (output/'games').glob('*.json') if (g := json.loads(p.read_text()))}
    cases = {c['id']: c for g in games.values() for c in g['cases']}
    config = json.loads((tokenizer_dir/'tokenizer_config.json').read_text())
    tokenizer = Tokenizer.from_file(str(tokenizer_dir/'tokenizer.json'))
    env = ImmutableSandboxedEnvironment(trim_blocks=True, lstrip_blocks=True)
    # Matches the Transformers chat-template tojson filter, not HTML escaping.
    env.filters['tojson'] = lambda x, ensure_ascii=False, indent=None, separators=None, sort_keys=False: json.dumps(
        x, ensure_ascii=ensure_ascii, indent=indent, separators=separators, sort_keys=sort_keys)
    template = env.from_string(config['chat_template'])
    lengths, semantic_checks = [], Counter()
    ids = set()
    content_groups = {}
    for row in examples:
        assert row['id'] not in ids
        ids.add(row['id'])
        assert row['split'] == 'development_audit_only'
        messages = row['messages']
        assert [m['role'] for m in messages] == ['system', 'user', 'assistant']
        payload = json.loads(messages[1]['content'])
        label = labels[row['id']]['answer']
        call = messages[2]['tool_calls'][0]['function']
        assert call['arguments'] == label and len(messages[2]['tool_calls']) == 1
        assert call['name'] == row['tools'][0]['function']['name']
        properties = row['tools'][0]['function']['parameters']['properties']
        assert set(label) == set(properties)
        if row['kind'] == 'semantic_belief':
            answer = label['possible_preferences']
            assert answer and len(answer) == len(set(answer))
            assert properties['possible_preferences']['items']['enum'] == ['want', 'neutral', 'avoid']
            assert set(answer) <= set(payload['initially_possible_preferences'])
            if not payload['history']:
                assert answer == payload['initially_possible_preferences']
                semantic_checks['empty_history_prior_preserved'] += 1
            else:
                assert answer == cases[row['case_id']]['support']
                semantic_checks['history_belief_matches_replayed_support'] += 1
        else:
            case = cases[row['case_id']]
            index = label['action_index']
            assert isinstance(index, int) and not isinstance(index, bool)
            assert 0 <= index < len(case['actions'])
            assert index in case['optimal_indices']
            assert properties['action_index']['maximum'] == len(case['actions'])-1
            assert payload['partner_judgment']['possible_preferences'] == case['support']
            assert len(payload['legal_actions']) == len(case['actions'])
            assert abs(case['q'][index] - max(case['q'])) < 1e-9
            decode_action(case['actions'][index])
            semantic_checks['planning_target_in_full_optimal_set'] += 1
        assert not ({'seed', 'source', 'source_game', 'case_id', 'condition', 'q', 'answer', 'worlds'} & set(payload))
        assert not ({'seed', 'private_preferences', 'metadata'} & set(payload['game']))
        prompt = template.render(messages=messages[:2], tools=row['tools'], add_generation_prompt=True)
        full = template.render(messages=messages, tools=row['tools'], add_generation_prompt=False)
        assert full.startswith(prompt)
        completion = full[len(prompt):]
        calls = re.findall(r'<tool_call>\s*(.*?)\s*</tool_call>', completion, re.S)
        assert len(calls) == 1
        parsed = json.loads(calls[0])
        assert parsed == dict(name=call['name'], arguments=label)
        assert completion.endswith('<|im_end|>\n')
        full_ids = tokenizer.encode(full, add_special_tokens=False).ids
        prompt_ids = tokenizer.encode(prompt, add_special_tokens=False).ids
        assert full_ids[:len(prompt_ids)] == prompt_ids, 'Token boundary is not a safe completion-only loss boundary.'
        assert tokenizer.decode(full_ids, skip_special_tokens=False) == full
        lengths.append(dict(id=row['id'], source_game=row['source_game'], kind=row['kind'],
                            prompt_tokens=len(prompt_ids), completion_tokens=len(full_ids)-len(prompt_ids),
                            total_tokens=len(full_ids), loss_mask_start=len(prompt_ids),
                            loss_mask_count=len(full_ids)-len(prompt_ids)))
        key = hashlib.sha256(prompt.encode()).hexdigest()
        if key in content_groups:
            assert content_groups[key]['answer'] == label, 'Identical prompt has conflicting label.'
        else:
            content_groups[key] = dict(answer=label, source=row['source_game'])
    provenance = json.loads((tokenizer_dir/'provenance.json').read_text())
    stats = dict(status='passed', examples=len(examples), semantic_checks=dict(semantic_checks),
                 examples_sha256=hashlib.sha256((output/'examples.jsonl').read_bytes()).hexdigest(),
                 tokenizer=provenance, tokenizer_sha256=hashlib.sha256((tokenizer_dir/'tokenizer.json').read_bytes()).hexdigest(),
                 tokenizer_config_sha256=hashlib.sha256((tokenizer_dir/'tokenizer_config.json').read_bytes()).hexdigest(),
                 template_rendering='Pinned official Jinja template with Transformers-compatible tojson; verified token prefix boundary and roundtrip.',
                 serving_parser_tested=False, gpu_training_tested=False,
                 lengths={kind: {key: quantiles([x[key] for x in lengths if x['kind'] == kind])
                                 for key in ('prompt_tokens', 'completion_tokens', 'total_tokens')}
                          for kind in ('semantic_belief', 'planning')},
                 over_total_budget={str(n): sum(x['total_tokens'] > n for x in lengths) for n in (2048, 4096, 8192)},
                 unique_prompt_hashes=len(content_groups))
    write_json(output/'tokenization_audit.json', stats)
    write_jsonl(output/'token_lengths.jsonl', lengths)
    (output/'tokenizer_config.json').write_text((tokenizer_dir/'tokenizer_config.json').read_text())
    write_json(output/'tokenizer_provenance.json', provenance)
    summary = json.loads((output/'summary.json').read_text())
    summary['tokenizer_status'] = 'passed_pinned_template_and_token_boundary_audit'
    summary['token_lengths'] = stats['lengths']
    summary['over_total_token_budget'] = stats['over_total_budget']
    write_json(output/'summary.json', summary)
    marker = '\n## 实际 tokenizer 验证\n'
    report = (output/'report.md').read_text().split(marker)[0]
    report += marker + '\n'
    report += f"固定 tokenizer revision：`{provenance['revision']}`。全部 {len(examples)} 条示例通过模板/token roundtrip、目标语义与 completion-only mask 边界检查。\n\n"
    report += '| 任务 | 总 tokens 中位数 | P95 | 最大 | 目标 tokens 最大 |\n|---|---:|---:|---:|---:|\n'
    for kind, length in stats['lengths'].items():
        total = length['total_tokens']
        report += f"| {kind} | {total['median']} | {total['p95']} | {total['max']} | {length['completion_tokens']['max']} |\n"
    report += '\n超过总序列上限的样本数：' + canonical(stats['over_total_budget']) + '。没有进行截断。\n'
    report += '\n这是本地模板和 token 检查；尚未通过远程 vLLM/Hermes 服务或 GPU trainer 的实际运行。\n'
    report += '\n## 本批数据揭示的问题\n\n'
    report += f"- {summary['all_actions_tied']}/{summary['sample_kinds']['planning']} 个 P 局面所有动作同值，应与主要策略训练分开处理。\n"
    if not any(summary['demonstrations'].get(k, 0) for k in ('CHOOSE_1', 'CHOOSE_2')):
        report += '- 没有 CHOOSE_1/CHOOSE_2 的 ego 示范，不能声称已覆盖 menu responder 能力。\n'
    if summary['demonstrations'].get('MENU', 0) and not summary['optimal_kind_sets'].get('MENU', 0):
        report += '- MENU 示范已出现，但本批没有仅 MENU 最优的局面；同值动作覆盖不能证明获得了主动取证策略。\n'
    report += f"- {summary['empty_history_beliefs']} 条 B 是空历史 controls，审计时有意保留；不能照此比例直接组成正式训练集。\n"
    report += f"- {summary['source_games']} 个不同源种子有 {summary['distinct_topologies']} 个去标号公共超图；{len(summary['duplicate_topology_groups'])} 组同构游戏未来划分时应放在同一源家族。\n"
    report += '- 生成主轨迹按采集策略保留，分支是定向增广；它们不能混作独立随机游戏估计。\n'
    (output/'report.md').write_text(report)
    write_json(output/'checksums.json', {str(p.relative_to(output)): hashlib.sha256(p.read_bytes()).hexdigest()
                                        for p in sorted(output.rglob('*')) if p.is_file() and p.name != 'checksums.json'})
    print(json.dumps(stats, ensure_ascii=False), flush=True)
    return stats


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--tokenizer-dir', type=Path, required=True)
    args = p.parse_args()
    validate(args.output_dir, args.tokenizer_dir)


if __name__ == '__main__':
    main()
