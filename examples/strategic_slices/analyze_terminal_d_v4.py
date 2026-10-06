"""Verify and merge existing D runs, then audit every controlled decision locally."""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
from pathlib import Path

from training.strategic_slices.common import digest, file_hash, write_json, write_rows
from training.strategic_slices.freeze import atomic_json
from training.strategic_slices.terminal_d import load_dataset
from training.strategic_slices.terminal_analysis import (
    read_archive, merge_evidence, audit_game, summarize_audit, require)


def audit_parent(data_path, rows, games, cfg, identity, target):
    data = load_dataset(data_path)
    tree = data.reference(rows[0])
    by_id = {r['id']: r for r in rows}
    cache, trajectories = {}, []
    for game in games:
        trajectories.append(audit_game(tree, by_id[game['slice_id']], game, cfg, cache))
    summaries = [summarize_audit(row, [t for t in trajectories if t['slice_id']==row['id']]) for row in rows]
    result = dict(identity=identity, parent_id=rows[0]['parent_id'], summaries=summaries, trajectories=trajectories)
    atomic_json(Path(target), dict(sha256=digest(result), result=result))
    return rows[0]['parent_id']


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--data',type=Path,default=Path('new/local_data/strategic_slices_oracle_consistent_candidates_v4'))
    cli.add_argument('--previous',type=Path,default=Path('new/local_data/strategic_slices_oracle_consistent_candidates_v2'))
    cli.add_argument('--old-results',type=Path,default=Path('new/strategic_slices_terminal_d_20261005'))
    cli.add_argument('--new-results',type=Path,default=Path('new/strategic_slices_terminal_d_v4_20261006'))
    cli.add_argument('--output',type=Path,default=Path('new/local_data/strategic_slices_terminal_d_v4_analysis'))
    cli.add_argument('--workers',type=int,default=2)
    cli.add_argument('--resume',action='store_true')
    cli.add_argument('--merge-only',action='store_true')
    args=cli.parse_args()
    require(args.workers>=1,'Workers must be positive')
    require(not args.output.exists() or args.resume,'Use a new output directory or --resume')
    data,previous=load_dataset(args.data),load_dataset(args.previous)
    old=read_archive(args.old_results,'terminal-d-full-results.tar.gz','continuation-32')
    new=read_archive(args.new_results,'terminal-d-v4-full-results.tar.gz','v4-refill32')
    grouped,merged=merge_evidence(data,previous,old,new,args.output)
    identity=dict(merge_sha256=file_hash(args.output/'MERGE.json'),
        analysis_sha256=file_hash(Path(__file__).resolve().parents[2]/'training/strategic_slices/terminal_analysis.py'),
        launcher_sha256=file_hash(Path(__file__)))
    print(json.dumps(dict(merged_slices=len(merged),trajectories=sum(len(x) for x in grouped.values()),
        verified_archive_files=[old['verified_files'],new['verified_files']])),flush=True)
    if args.merge_only:return
    parent_dir=args.output/'parents';parent_dir.mkdir(exist_ok=True)
    future_ids={}
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for pid,games in sorted(grouped.items()):
            target=parent_dir/f'{pid}.json'
            if target.exists():
                cached=json.loads(target.read_text())
                require(cached['sha256']==digest(cached['result']) and cached['result']['identity']==identity,'Stale audit checkpoint')
                continue
            rows=[r for r in data.candidates if r['parent_id']==pid]
            future_ids[pool.submit(audit_parent,args.data,rows,games,new['protocol']['config'],identity,target)]=pid
        completed=len(grouped)-len(future_ids)
        for future in as_completed(future_ids):
            pid=future.result();completed+=1
            print(f'audited {completed}/{len(grouped)} parents: {pid}',flush=True)
    summaries=[]
    for path in sorted(parent_dir.glob('*.json')):
        item=json.loads(path.read_text());require(item['result']['identity']==identity,'Stale parent result')
        summaries.extend(item['result']['summaries'])
    require(len(summaries)==800,'Missing audited questions')
    write_rows(args.output/'trajectory_metrics.jsonl',summaries)
    counts={}
    for split in ('train','validation','test','all','strong_acquisition'):
        rs=[r for r in summaries if split=='all' or (r['strong_acquisition'] if split=='strong_acquisition' else r['split']==split)]
        counts[split]=dict(slices=len(rs),**{key:sum(r[key] for r in rs) for key in (
            'completed','mixed_completion','any_step_value_contrast','later_step_value_contrast',
            'decision_gap_or_completion_contrast','model_query_calls','after_query_valid_calls',
            'after_query_suboptimal_calls','answer_sensitive_calls','answer_sensitive_valid_calls',
            'answer_sensitive_optimal_calls','answer_sensitive_failed_calls')})
    write_json(args.output/'SUMMARY.json',dict(identity=identity,counts=counts,
        statuses=dict(Counter(g['status'] for gs in grouped.values() for g in gs)),
        interpretation='Decision gap sums are trajectory diagnostics, not D or C/S. Failed trajectories have null full-window gap, with valid prefix gaps recorded separately. Same-prompt comparisons use all controlled decisions; rewards retain independent hidden-world/reference noise.',
        native_replay_verified=True,new_model_calls=0,new_equilibrium_solves=0))
    atomic_json(args.output/'COMPLETE.json',dict(files={str(p.relative_to(args.output)):file_hash(p)
        for p in [args.output/'MERGE.json',args.output/'provenance.jsonl',args.output/'merged_slices.jsonl',
                  args.output/'trajectory_metrics.jsonl',args.output/'SUMMARY.json',*sorted(parent_dir.glob('*.json'))]}))
    print(json.dumps(counts,indent=2))


if __name__=='__main__':main()
