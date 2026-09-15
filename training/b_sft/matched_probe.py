"""Prepare a held-out development probe matched to fixed fitting pairs."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from .data import load_records, check_split, check_corpus_export
from .semantic import gold_answer, read_pairs, score_records, write_json, write_jsonl


def signature(pair, by_id):
    a, b = (by_id[pair[k]] for k in ('before', 'after'))
    g = json.loads(a['messages'][1]['content'])['game']
    mode = 'binary' if all(x.get('binary', True) for x in g['goals']) else (
        'linear' if all(not x.get('binary', True) for x in g['goals']) else 'mixed')
    before, after = (gold_answer(x)['possible_preferences'] for x in (a, b))
    return (g['n_players'], mode, 'maintain' if set(before)==set(after) else 'update', len(before), len(after))


def match_pairs(reference, reference_pairs, candidates, candidate_pairs):
    check_split(reference, candidates)
    a, b = ({r['id']:r for r in rows} for rows in (reference, candidates))
    selected, used, sources, mappings = [], set(), Counter(), []
    for pair in reference_pairs:
        key = signature(pair, a)
        available = [p for p in candidate_pairs if p['before'] not in used and p['after'] not in used
                     and signature(p, b)==key]
        if not available:
            raise ValueError(f'No disjoint matched pair for {key}; do not silently relax matching')
        chosen = min(available, key=lambda p: (sources[p['source_id']],
            hashlib.sha256((p['before']+'\n'+p['after']).encode()).hexdigest()))
        selected.append(chosen)
        used.update((chosen['before'], chosen['after']))
        sources[chosen['source_id']] += 1
        mappings.append(dict(reference=[pair['before'],pair['after']],
                             heldout=[chosen['before'],chosen['after']], matched_stratum=key))
    rows = [r for r in candidates if r['id'] in used]
    score_records(rows, [], selected)
    return rows, selected, mappings


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--reference-dir', type=Path, required=True)
    p.add_argument('--validation-file', type=Path, required=True)
    p.add_argument('--validation-pairs', type=Path, required=True)
    p.add_argument('--output-dir', type=Path, required=True)
    args=p.parse_args()
    if args.output_dir.exists():
        p.error('Use a fresh output-dir')
    check_corpus_export(args.validation_pairs)
    rows,pairs,mappings=match_pairs(load_records(args.reference_dir/'questions.jsonl'),
        read_pairs(args.reference_dir/'pairs.jsonl'),load_records(args.validation_file),read_pairs(args.validation_pairs))
    args.output_dir.mkdir(parents=True)
    write_jsonl(args.output_dir/'questions.jsonl', rows)
    write_jsonl(args.output_dir/'pairs.jsonl', pairs)
    write_json(args.output_dir/'manifest.json',dict(purpose='matched held-out development diagnostic',
        reference_sha256=hashlib.sha256((args.reference_dir/'questions.jsonl').read_bytes()).hexdigest(),
        validation_sha256=hashlib.sha256(args.validation_file.read_bytes()).hexdigest(),
        samples=len(rows),pairs=len(pairs),sources=len({r['source_id'] for r in rows}),mappings=mappings,
        unmatched_factors=['exact preference values','history length','action content','commitment count'],
        final_test=False))
    print(f'Matched held-out probe: {len(rows)} questions, {len(pairs)} pairs')


if __name__=='__main__':
    main()
