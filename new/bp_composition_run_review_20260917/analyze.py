"""Verify downloaded prompts/results and summarize this one completed rollout."""
import ast
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
PACK = ROOT / 'new/bp_composition_diagnostic_v1'
sys.path.insert(0, str(PACK))
from evaluate import load, summarize


def main():
    download = ROOT / 'new/local_data/social_runs/bp_composition_v1'
    run = download / Path((download / 'latest.txt').read_text().strip()).name
    evaluation = run / 'run/evaluation'
    manifest, tasks, requests = load()
    manifest_hash = hashlib.sha256((PACK / 'manifest.json').read_bytes()).hexdigest()
    config = json.loads((evaluation / 'run_config.json').read_text())
    assert config['manifest_sha256'] == manifest_hash
    assert (run / 'EXIT_CODE').read_text().strip() == '0'
    assert json.loads((evaluation / 'COMPLETE.json').read_text()) == config
    rows = list(map(json.loads, (evaluation / 'responses.jsonl').read_text().splitlines()))
    summary, scored = summarize(rows, tasks, config['repeats'])
    assert summary == json.loads((evaluation / 'summary.json').read_text())
    assert scored == list(map(json.loads, (evaluation / 'scored.jsonl').read_text().splitlines()))
    indexed = {(r['task_id'], r['replica']): r for r in rows}
    expected_seeds = {}
    for key, r in indexed.items():
        seed = int(hashlib.sha256(f'{config["seed"]}:{key[0]}:{key[1]}'.encode()).hexdigest()[:8], 16)
        assert r['seed'] == seed
        assert r['endpoint_index'] == key[1] % 2
        expected_seeds[seed] = r
    assert len(expected_seeds) == 96
    prompt_counts = Counter(); verified_seeds = set()
    for endpoint in range(2):
        for line in (run / f'run/server-{endpoint}.log').read_text().splitlines():
            if 'Received request' not in line or 'prompt:' not in line: continue
            text = ast.literal_eval(line.split('prompt: ', 1)[1].split(', params: SamplingParams', 1)[0])
            matches = [tid for tid, q in requests.items() if q['request']['messages'][1]['content'] in text]
            assert len(matches) == 1
            tid = matches[0]; q = requests[tid]['request']
            assert q['messages'][0]['content'] in text
            tools = [json.loads(l) for l in text.splitlines() if l.startswith('{"type": "function"')]
            assert tools == q['tools']
            for token in ('temperature=1.0', 'top_p=1.0', 'top_k=-1', 'repetition_penalty=1.0', 'max_tokens=1024'):
                assert token in line
            seed = int(re.search(r'\bseed=(\d+)', line).group(1))
            assert seed not in verified_seeds
            assert expected_seeds[seed]['task_id'] == tid and expected_seeds[seed]['endpoint_index'] == endpoint
            verified_seeds.add(seed); prompt_counts[tid] += 1
    assert len(verified_seeds) == 96 and set(prompt_counts.values()) == {8}
    actions = defaultdict(Counter); target_known = defaultdict(Counter); b_predictions = defaultdict(Counter)
    for r in rows:
        t = tasks[r['task_id']]; c = r['completion']; cond = t['condition']; case = t['case_id']
        if c['finish_reason'] == 'length':
            actions[cond]['TRUNCATED'] += 1; continue
        call = c['raw_message']['tool_calls'][0]['function']; args = json.loads(call['arguments'])
        actions[cond][call['name']] += 1
        if call['name'] == 'SUBMIT_BELIEFS':
            j = args['judgments'][0]
            b_predictions[case][json.dumps(dict(possible_preferences=sorted(j['possible_preferences']), favored=j['favored']), sort_keys=True)] += 1
        elif call['name'] == 'INVESTIGATE':
            from training.b_sft.social_named_probe import present
            v = present(t)
            known = args['goal'] in v['public_preferences'].get(args['player'], {})
            target_known[cond]['publicly_known' if known else 'unknown'] += 1
    evidence_keys = [
        ('binary_complementarity:preset:B', 0),
        ('binary_complementarity:preset:P_gold', 0),
        ('binary_complementarity:preset:P_gold', 1),
        ('binary_complementarity:voluntary:P_gold', 0),
        ('mixed_partial_completion:preset:P_gold', 2),
        ('mixed_partial_completion:voluntary:P_gold', 0),
    ]
    evidence = [dict(task_id=k[0], replica=k[1], response=indexed[k],
                     request=requests[k[0]]['request']) for k in evidence_keys]
    result = dict(run=str(run.relative_to(ROOT)), manifest_sha256=manifest_hash,
        integrity=dict(exit_code=0, complete=True, saved_scores_match=True, saved_summary_matches=True,
                       server_prompt_tool_sampling_and_seed_matches=96, per_task_calls=dict(prompt_counts)),
        summary=summary, action_counts={k: dict(v) for k, v in actions.items()},
        investigation_targets={k: dict(v) for k, v in target_known.items()},
        b_predictions={k: dict(v) for k, v in b_predictions.items()},
        source_hashes={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in (evaluation / 'responses.jsonl', evaluation / 'summary.json',
                                 run / 'run/server-0.log', run / 'run/server-1.log')})
    (OUT / 'analysis.json').write_text(json.dumps(result, indent=2) + '\n')
    (OUT / 'evidence.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in evidence))
    print(json.dumps(dict(integrity=result['integrity'], actions=result['action_counts'],
                         investigations=result['investigation_targets']), indent=2))


if __name__ == '__main__':
    main()
