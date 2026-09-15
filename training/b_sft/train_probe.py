"""Small train-pool diagnostic using an exported HF model on one GPU."""
import argparse
from collections import defaultdict
from contextlib import nullcontext
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from .data import load_records, check_corpus_export, check_split
from .generation import generate_predictions, prepare_prompts
from .semantic import gold_answer, read_pairs, score_records, write_json, write_jsonl, write_report


def select_probe(records, pairs, max_pairs=24):
    by_id = {r['id']: r for r in records}
    groups = defaultdict(list)
    for pair in pairs:
        if pair['before'] not in by_id or pair['after'] not in by_id:
            continue
        a, b = by_id[pair['before']], by_id[pair['after']]
        before = gold_answer(a)['possible_preferences']
        after = gold_answer(b)['possible_preferences']
        info = json.loads(a['messages'][1]['content'])
        kind = 'maintain' if set(before) == set(after) else 'update'
        groups[(info['game']['n_players'], kind, len(after))].append(pair)
    for group in groups.values():
        group.sort(key=lambda p: hashlib.sha256((p['before']+'\n'+p['after']).encode()).hexdigest())
    chosen, sources = [], defaultdict(int)
    while len(chosen) < max_pairs and any(groups.values()):
        for key in sorted(groups):
            group = groups[key]
            if not group or len(chosen) >= max_pairs:
                continue
            pair = min(group, key=lambda p: sources[p['source_id']])
            group.remove(pair)
            chosen.append(pair)
            sources[pair['source_id']] += 1
    ids = {p[k] for p in chosen for k in ('before', 'after')}
    return [r for r in records if r['id'] in ids], chosen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--train-file')
    parser.add_argument('--pairs-file')
    parser.add_argument('--prepare-dir', type=Path)
    parser.add_argument('--probe-dir', type=Path)
    parser.add_argument('--generalization-dir', type=Path, help='Run matched held-out questions after same-question probe, reusing the model')
    parser.add_argument('--model')
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--max-new-tokens', type=int, default=128)
    args = parser.parse_args()
    if args.prepare_dir:
        if not args.train_file or not args.pairs_file:
            parser.error('Preparation requires train-file and pairs-file')
        if args.prepare_dir.exists():
            parser.error('Use a fresh prepare-dir')
        check_corpus_export(args.pairs_file)
        rows, pairs = select_probe(load_records(args.train_file), read_pairs(args.pairs_file))
        if not rows:
            raise ValueError('No complete training pairs')
        score_records(rows, [], pairs)
        args.prepare_dir.mkdir(parents=True)
        write_jsonl(args.prepare_dir/'questions.jsonl', rows)
        write_jsonl(args.prepare_dir/'pairs.jsonl', pairs)
        write_json(args.prepare_dir/'manifest.json', dict(
            purpose='train-pool diagnostic; exposure at checkpoint is not verified',
            samples=len(rows), pairs=len(pairs), sources=len({r['source_id'] for r in rows}),
            train_sha256=hashlib.sha256(Path(args.train_file).read_bytes()).hexdigest(),
            selection='round-robin player count, maintain/update, after-gold-size; diversify source'))
        print((args.prepare_dir/'manifest.json').read_text())
        return
    if not args.model or not args.probe_dir or not args.output_dir:
        parser.error('Inference requires model, probe-dir and output-dir')
    if args.output_dir.exists():
        parser.error('Use a fresh output-dir')
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise ValueError('Explicitly select exactly one allocated GPU with CUDA_VISIBLE_DEVICES')
    rows = load_records(args.probe_dir/'questions.jsonl')
    pairs = read_pairs(args.probe_dir/'pairs.jsonl')
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token_id = tokenizer.eos_token_id
    prompts = prepare_prompts(rows, tokenizer, 8192, args.max_new_tokens)
    extra = None
    if args.generalization_dir:
        extra_rows = load_records(args.generalization_dir/'questions.jsonl')
        check_split(rows, extra_rows)
        extra_pairs = read_pairs(args.generalization_dir/'pairs.jsonl')
        score_records(extra_rows, [], extra_pairs)
        extra = (extra_rows, extra_pairs, prepare_prompts(extra_rows, tokenizer, 8192, args.max_new_tokens))
    model = AutoModelForCausalLM.from_pretrained(args.model, torch_dtype=torch.bfloat16,
                                               attn_implementation='sdpa', low_cpu_mem_usage=True)
    model.to('cuda').eval()
    model.requires_grad_(False)
    trainer = SimpleNamespace(model_wrapped=model,
        args=SimpleNamespace(process_index=0, world_size=1, device=torch.device('cuda:0')),
        accelerator=SimpleNamespace(unwrap_model=lambda m: m, autocast=nullcontext))
    predictions = generate_predictions(trainer, prompts, tokenizer, args.max_new_tokens, 'standard')
    metrics = write_report(args.output_dir, rows, predictions, pairs, metadata=dict(
        model=args.model, evaluation_split='train_pool_probe', selection_eligible=False,
        training=False, exposure_at_checkpoint_verified=False))
    print(json.dumps({k:metrics[k] for k in ('overall','by_gold_size','pairs','shortcut_diagnostics')}, indent=2))
    if extra:
        extra_rows, extra_pairs, extra_prompts = extra
        print('MATCHED GENERALIZATION START', flush=True)
        predictions = generate_predictions(trainer, extra_prompts, tokenizer, args.max_new_tokens, 'standard')
        heldout = write_report(args.output_dir/'generalization', extra_rows, predictions, extra_pairs,
                              metadata=dict(model=args.model, evaluation_split='matched_validation_probe',
                                            selection_eligible=False, training=False))
        comparison = dict(same_questions={k:metrics[k] for k in ('overall','by_gold_size','pairs','shortcut_diagnostics')},
                          matched_generalization={k:heldout[k] for k in ('overall','by_gold_size','pairs','shortcut_diagnostics')},
                          limitation='Small development diagnostic; matched factors do not establish cause of a gap')
        write_json(args.output_dir/'comparison.json', comparison)
        print(json.dumps(comparison, indent=2))


if __name__ == '__main__':
    main()
