"""Audit early investigation against saved terminal references, without search."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import time

from training.strategic_slices.common import file_hash, write_json
from training.strategic_slices.early_investigation import measure_early_investigation
from training.strategic_slices.terminal_candidates import TerminalCandidates


def statistics(rows):
    units = {(r['parent_id'], r['ego']) for r in rows}
    mass = sum(r['oracle_information_set_mass'] for r in rows)
    return dict(information_cells=len(rows), parent_player_pairs=len(units),
        classifications=dict(Counter(r['classification'] for r in rows)),
        reach_weighted_classification_fractions={kind: sum(r['oracle_information_set_mass'] for r in rows
            if r['classification']==kind)/mass for kind in ('strict_query_advantage', 'tie', 'query_inferior')} if mass else {},
        strictly_positive_parents=len({r['parent_id'] for r in rows if r['delta_investigate']>1e-8}),
        strong_positive_parents=len({r['parent_id'] for r in rows if r['delta_investigate']>.05}),
        maximum_delta=max((r['delta_investigate'] for r in rows), default=None),
        minimum_delta=min((r['delta_investigate'] for r in rows), default=None),
        strong_query_access_cells=sum(r['query_access_value']>.05 for r in rows),
        positive_query_access_cells=sum(r['query_access_value']>1e-8 for r in rows),
        maximum_query_access_value=max((r['query_access_value'] for r in rows), default=None),
        mean_query_access_value=sum(r['oracle_information_set_mass']*r['query_access_value'] for r in rows)/mass if mass else None,
        omitted_by_neighborhood=sum(r['omitted_by_three_proposal_neighborhood'] for r in rows),
        maximum_Q_change_from_reoptimizing=max((r['maximum_root_Q_change_from_reoptimizing'] for r in rows), default=None))


def run(source, out, limit=None):
    out.mkdir(parents=True, exist_ok=True)
    data = TerminalCandidates(source)
    sources = [Path(__file__), Path('training/strategic_slices/early_investigation.py'),
               Path('training/strategic_slices/oracle_consistent.py'), Path('training/strategic_slices/terminal_candidates.py')]
    config = dict(source_manifest_sha256=file_hash(source/'manifest.json'),
                  code_sha256={str(p): file_hash(p) for p in sources},
                  scope='All oracle-reachable first proposals, all players and types; no C filter or entrance cap. Full terminal focal BR versus frozen partners. Prohibit own queries separately over all future decisions.')
    if (out/'config.json').exists() and json.loads((out/'config.json').read_text()) != config:
        raise ValueError('Source changed; use a fresh output directory')
    write_json(out/'config.json', config)
    examples = {r['parent_id']: r for r in data.candidates}
    results = []
    for pid in sorted(data.parents)[:limit]:
        path = out/(pid+'.json')
        if path.exists():
            result = json.loads(path.read_text())
        else:
            start = time.monotonic()
            tree = data.reference(examples[pid]); tree.deadline = time.monotonic()+600
            rows = measure_early_investigation(tree, pid)
            by_player = defaultdict(float)
            for row in rows:
                by_player[row['ego']] += row['oracle_information_set_mass']
            if set(by_player) != set(range(tree.n)) or any(abs(m-1)>1e-8 for m in by_player.values()):
                raise AssertionError('First-proposal cells do not partition each player reach')
            result = dict(parent_id=pid, reference_id=examples[pid]['reference_id'],
                policy_sha256=tree.certificate['policy_sha256'], nodes=len(tree.entries),
                players=tree.n, rounds=len(tree.rules.spec.round_robin)//tree.n,
                split=data.parents[pid]['split'], rows=rows, seconds=time.monotonic()-start,
                first_proposal_reach_partition_verified=True)
            temp=path.with_suffix('.tmp'); write_json(temp, result); temp.replace(path)
        results.append(result)
        rows = [row for r in results for row in r['rows']]
        summary = dict(**config, parents=len(results), total_parents=len(data.parents),
            complete=len(results)==len(data.parents), all=statistics(rows),
            by_game_size={f'{n}p/{k}r': statistics([row for r in results if r['players']==n and r['rounds']==k for row in r['rows']])
                          for n, k in sorted({(r['players'], r['rounds']) for r in results})},
            solver_calls=0, model_calls=0, candidates_changed=False)
        write_json(out/'summary.json', summary)
        print(pid, f"{result['players']}p/{result['rounds']}r", statistics(result['rows']), flush=True)


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, default=Path('new/local_data/strategic_slices_oracle_consistent_candidates_v3'))
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--limit', type=int)
    a=p.parse_args(); run(a.source, a.output, a.limit)
