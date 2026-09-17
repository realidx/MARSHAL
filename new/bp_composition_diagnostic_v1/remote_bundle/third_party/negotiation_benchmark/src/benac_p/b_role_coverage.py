"""Add missing learner roles using new TRAIN source games only.

Existing validation/test questions are unchanged. Source selection uses the
public initial actor and topology, never labels, outcomes or model failures.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from benac_p.b_data_audit import audit_game
from benac_p.b_training_data import OPTIONS, aggregate_scores, make_game
from benac_p.mcts_bp_audit import CELLS, write_json, write_jsonl
from benac_p.mcts_oracle import Budget
from benac_p.sft_data_audit import topology_hash


def load_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--seed-start', type=int, default=63004)
    args = parser.parse_args(argv)
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        parser.error('Use a fresh output directory.')
    original_manifest = json.loads((args.source_dir/'manifest.json').read_text())
    original_summary = json.loads((args.source_dir/'summary.json').read_text())
    assert original_summary['complete']
    for name, checksum in json.loads((args.source_dir/'checksums.json').read_text()).items():
        assert hashlib.sha256((args.source_dir/name).read_bytes()).hexdigest() == checksum
    for name, checksum in original_manifest['source_sha256'].items():
        assert hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() == checksum
    configuration = original_manifest['configuration']
    budget = Budget(**original_manifest['fixed_policy_budget'])
    games = [json.loads(p.read_text()) for p in sorted((args.source_dir/'games').glob('*.json'))]
    raw = load_jsonl(args.source_dir/'b_all_unique.jsonl')
    pairs = load_jsonl(args.source_dir/'update_pairs.jsonl')
    splits = {s: load_jsonl(args.source_dir/f'b_{s}.jsonl') for s in ('train', 'validation', 'test')}
    source_split = dict(original_summary['source_split'])
    seen_topologies = {g['topology'] for g in games}
    additions = []
    for cell in CELLS:
        present = {g['learner'] for g in games if g['cell'] == cell and source_split[g['source_id']] == 'train'}
        needed = set(range(4)) - present
        for seed in range(args.seed_start, args.seed_start+100):
            if not needed:
                break
            spec, oracle, actual, focal, public = make_game(seed, cell, budget,
                configuration['backgrounds'], configuration['focal_goals'])
            role = spec.round_robin[0]
            if role not in needed:
                continue
            topology = topology_hash(spec)
            if topology in seen_topologies:
                continue
            seen_topologies.add(topology)
            additions.append((seed, cell, role))
            needed.remove(role)
        assert not needed, f'Could not fill public-role quota for {cell}'
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = dict(original_manifest)
    manifest['configuration'] = dict(configuration, output_dir=str(args.output_dir))
    manifest['source_sha256'] = dict(original_manifest['source_sha256'],
        **{Path(__file__).name: hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    manifest['base_manifest_sha256'] = hashlib.sha256((args.source_dir/'manifest.json').read_bytes()).hexdigest()
    manifest['base_source_dir'] = str(args.source_dir)
    manifest['added_train_sources'] = [dict(seed=s, cell=c, learner=r) for s, c, r in additions]
    manifest['splits'] = 'Original train/validation/test source assignments unchanged. Additional role-stratified sources are train only and use unseen goal topologies.'
    write_json(args.output_dir/'manifest.json', manifest)
    for seed, cell, role in additions:
        print('ADD_TRAIN', cell, seed, 'learner', role, flush=True)
        game, rows, selected, updates = audit_game(seed, cell, budget,
            configuration['backgrounds'], configuration['focal_goals'],
            configuration['max_branches'], configuration['per_size'])
        assert game['learner'] == role
        games.append(game); raw.extend(rows); pairs.extend(updates)
        splits['train'].extend(selected)
        source_split[game['source_id']] = 'train'
        write_json(args.output_dir/'role_progress.json', [g['stats'] for g in games])
    assert len({r['id'] for r in raw}) == len(raw)
    topology_splits = {}
    for g in games:
        split = source_split[g['source_id']]
        assert topology_splits.setdefault(g['topology'], split) == split
        write_json(args.output_dir/'games'/f'{g["source_id"]}.json', g)
    for split, rows in splits.items():
        write_jsonl(args.output_dir/f'b_{split}.jsonl', rows)
        if split != 'train':
            assert (args.output_dir/f'b_{split}.jsonl').read_bytes() == (args.source_dir/f'b_{split}.jsonl').read_bytes()
    write_jsonl(args.output_dir/'b_all_unique.jsonl', raw)
    write_jsonl(args.output_dir/'update_pairs.jsonl', pairs)
    majority = list(Counter(tuple(r['answer']['possible_preferences']) for r in splits['train']).most_common(1)[0][0])
    summary = dict(version=original_summary['version'], complete=True, games=len(games), expected_games=len(games),
        source_split=source_split, source_and_topology_disjoint=True, global_input_duplicates=0,
        raw_unique_samples=len(raw), selected_samples=sum(map(len, splits.values())),
        training_started=False, learner_roles_covered_in_each_train_cell=True,
        validation_test_unchanged=True, per_game=[g['stats'] for g in games],
        splits={s: dict(samples=len(rs), sources=sorted({r['source_id'] for r in rs}),
                        support_sizes=dict(Counter(len(r['answer']['possible_preferences']) for r in rs)),
                        learner_roles=sorted({r['input']['learner_id'] for r in rs})) for s, rs in splits.items()},
        baselines={s: dict(always_all=aggregate_scores(rs, lambda _: OPTIONS),
                           train_majority=aggregate_scores(rs, lambda _: majority)) for s, rs in splits.items()},
        readiness='B-only corpus with all learner roles in each training cell. No model learning or transfer result.')
    for cell in CELLS:
        assert {g['learner'] for g in games if g['cell'] == cell and source_split[g['source_id']] == 'train'} == set(range(4))
    write_json(args.output_dir/'summary.json', summary)
    files = sorted(p for p in args.output_dir.rglob('*') if p.is_file())
    write_json(args.output_dir/'checksums.json', {str(p.relative_to(args.output_dir)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files})
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    main()
