"""Select eight balanced, unchanged windows per parent from a verified pool."""
import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from itertools import combinations
import json
from pathlib import Path
import shutil

import numpy as np

from training.strategic_slices.common import digest, file_hash, stable, write_json, write_rows
from training.strategic_slices.terminal_candidates import TerminalCandidates


POLICY = {
    'exact_per_parent': 8,
    'required': ['all available ego, k and decision-kind categories',
                 'all collective controls and detectable-information rows',
                 'at least two distinct public histories'],
    'lexicographic_objectives': [
        'minimize sum of squared ego counts within parent',
        'minimize sum of squared k counts within parent',
        'minimize sum of squared proposal/response counts within parent',
        'maximize distinct ego/k pairs',
        'maximize distinct remaining-proposal counts',
        'maximize distinct entrance identities',
        'maximize distinct public histories',
        'minimize cumulative seat-count squares within player-count group, then k, then kind',
        'stable candidate-ID digest'],
    'parent_order': 'sorted parent ID',
    'scope': 'Exhaustive subsets per parent; cumulative tie break is not a global optimum claim.',
}


def features(row):
    return {
        'ego': {row['ego']}, 'k': {row['k']}, 'kind': {row['decision_kind']},
        'pair': {(row['ego'], row['k'])},
        'remaining': {m['remaining_proposals'] for m in row['members']},
        'entrance': {row.get('entrance_id', row['id'])},
        'history': {stable(m['history']) for m in row['members']},
    }


def select_parent(rows, players, totals):
    rows = sorted(rows, key=lambda r: r['id'])
    if len(rows) < 8:
        raise ValueError('Parent has fewer than eight existing candidates')
    subsets = np.asarray(list(combinations(range(len(rows)), 8)), dtype=int)
    fs = [features(r) for r in rows]
    counts = {}
    labels = {}
    for key in fs[0]:
        labels[key] = sorted(set().union(*(f[key] for f in fs)))
        indicators = np.array([[label in f[key] for label in labels[key]] for f in fs], dtype=int)
        counts[key] = indicators[subsets].sum(axis=1)
    valid = np.ones(len(subsets), dtype=bool)
    for key in ('ego', 'k', 'kind'):
        valid &= (counts[key] > 0).all(axis=1)
    valid &= (counts['history'] > 0).sum(axis=1) >= 2
    for i, row in enumerate(rows):
        if row['entry_kind'] == 'oracle-reach-collective' or row['detectable_information_value']:
            valid &= (subsets == i).any(axis=1)
    choices = np.flatnonzero(valid)
    if not len(choices):
        raise ValueError('Eight-row subset cannot preserve required coverage')
    scores = [(counts[key] ** 2).sum(axis=1) for key in ('ego', 'k', 'kind')]
    scores += [-(counts[key] > 0).sum(axis=1) for key in ('pair', 'remaining', 'entrance', 'history')]
    for key in ('ego', 'k', 'kind'):
        counter = totals[('ego', players)] if key == 'ego' else totals[key]
        base = np.array([counter[label] for label in labels[key]])
        scores.append(((counts[key] + base) ** 2).sum(axis=1))
    best_scores = []
    for score in scores:
        best = score[choices].min()
        choices = choices[score[choices] == best]
        best_scores.append(int(best))
    best = min(choices, key=lambda i: digest([rows[j]['id'] for j in subsets[i]]))
    selected = [rows[j] for j in subsets[best]]
    for key in ('ego', 'k', 'kind'):
        counter = totals[('ego', players)] if key == 'ego' else totals[key]
        counter.update(next(iter(features(r)[key])) for r in selected)
    return selected, dict(examined_subsets=len(subsets), feasible_subsets=int(valid.sum()),
                          objective_values=best_scores, selected_ids=[r['id'] for r in selected])


def distribution(rows, parents):
    return dict(
        candidates=len(rows), per_parent=dict(Counter(Counter(r['parent_id'] for r in rows).values())),
        k=dict(Counter(r['k'] for r in rows)),
        decision_kinds=dict(Counter(r['decision_kind'] for r in rows)),
        ego_by_players={str(n): dict(Counter(r['ego'] for r in rows if parents[r['parent_id']]['players'] == n))
                        for n in (2, 3)},
        entry_kinds=dict(Counter(r['entry_kind'] for r in rows)),
        remaining_proposals_member_counts=dict(Counter(m['remaining_proposals'] for r in rows for m in r['members'])),
        distinct_public_entrances=len({(r['parent_id'], m['root_index']) for r in rows for m in r['members']}),
        members=sum(len(r['members']) for r in rows))


def package(source, out):
    dataset = TerminalCandidates(source)
    source_hash = file_hash(source/'manifest.json')
    marker = json.loads((source/'CANDIDATES_VERIFIED.json').read_text())
    if marker['manifest_sha256'] != source_hash:
        raise ValueError('Source verification marker mismatch')
    if len(dataset.parents) != 100 or dataset.manifest['status'] != 'oracle-consistent-candidate-pool-verified':
        raise ValueError('Expected 100 verified parents')
    groups = defaultdict(list)
    for row in dataset.candidates:
        groups[row['parent_id']].append(row)
    selected = []; ledger = []; totals = defaultdict(Counter)
    for pid in sorted(dataset.parents):
        kept, diagnostic = select_parent(groups[pid], dataset.parents[pid]['players'], totals)
        selected.extend(kept)
        ledger.append(dict(parent_id=pid, source_count=len(groups[pid]), retained=len(kept), **diagnostic))
    # Preserve the exact records and all original proof artifacts. The original
    # audit describes the superset; it must not masquerade as a fresh 800-row run.
    shutil.copytree(source, out)
    proof = out/'provenance'/'source_verification'
    proof.mkdir()
    for name in ('manifest.json', 'CANDIDATES_VERIFIED.json', 'audit.json', 'audits', 'REPORT.md'):
        shutil.move(str(out/name), str(proof/name))
    write_rows(out/'candidates.jsonl', selected)
    write_rows(out/'selection_ledger.jsonl', ledger)
    script = Path(__file__)
    shutil.copyfile(script, out/'source/examples/strategic_slices'/script.name)
    before = distribution(dataset.candidates, dataset.parents)
    after = distribution(selected, dataset.parents)
    write_json(out/'balance.json', dict(policy=POLICY, before=before, after=after))
    original = {r['id']: r for r in dataset.candidates}
    assert len(selected) == 800 and set(Counter(r['parent_id'] for r in selected).values()) == {8}
    assert all(stable(r) == stable(original[r['id']]) for r in selected)
    assert len({r['id'] for r in selected}) == 800
    assert all(file_hash(out/ref['file']) == file_hash(source/ref['file']) for ref in dataset.references.values())
    assert file_hash(out/'parents.jsonl') == file_hash(source/'parents.jsonl')
    assert file_hash(out/'references.jsonl') == file_hash(source/'references.jsonl')
    for pid, parent in dataset.parents.items():
        if parent['total_proposals'] > parent['players']:
            assert {2, 3} <= {r['k'] for r in selected if r['parent_id'] == pid}
    audit = dict(mode='unchanged-subset-of-independently-audited-pool', parents=100, candidates=800,
                 candidate_records_identical=True, parent_and_reference_files_identical=True,
                 exactly_eight_per_parent=True, source_manifest_sha256=source_hash,
                 inherited_reference_certifications=100, new_oracle_solves=0, new_CS_measurements=0,
                 D_measured=False, preserved_all_available_ego_k_kind_categories=True,
                 preserved_all_collective_and_detectable_information_rows=True)
    write_json(out/'audit.json', audit)
    manifest = deepcopy(dataset.manifest)
    manifest.update(candidates=800, derivation=dict(source=str(source), source_manifest_sha256=source_hash,
                    audit_mode=audit['mode']), subset_selection=POLICY)
    manifest['selection'].update(max_per_parent=8, exact_per_parent=8,
        cap_policy='Balanced subset of existing verified candidates; see subset_selection.',
        source_pool_max_per_parent=dataset.manifest['selection']['max_per_parent'])
    manifest['coverage'].update(k=after['k'], decision_kinds=after['decision_kinds'])
    for key in ('information_positive_rows', 'detectable_information_rows'):
        field = 'information_positive' if key.startswith('information_positive') else 'detectable_information_value'
        manifest['coverage'][key] = sum(r[field] for r in selected)
    manifest['coverage']['information_positive_parents'] = len({r['parent_id'] for r in selected if r['information_positive']})
    for channel in manifest['coverage']['information_channels']:
        values = [r['information_channels'][channel] for r in selected if r['information_channels'].get(channel) is not None]
        manifest['coverage']['information_channels'][channel] = dict(measured_rows=len(values), maximum=max(values, default=None))
    for split in manifest['splits']:
        manifest['splits'][split]['candidates'] = sum(r['split'] == split for r in selected)
    manifest['packaging_and_audit_source_identity'][str(script.relative_to(Path.cwd()))] = file_hash(script)
    report = f'''# Balanced candidate subset — 2026-10-05

100 unchanged parents, exactly 8 candidates each: **800 candidates**.
Source: `{source}` (1,596 candidates). No D evaluation or final 100-slice selection.

Selection exhaustively compares eight-row subsets within each parent. It retains
all available player, k and proposal/response categories, all four collective
controls, and at least two public histories. In order, it balances player counts,
k counts, and decision kinds by minimizing squared counts; then maximizes ego/k,
remaining-turn and entrance diversity. Cumulative distribution and stable hashes
break ties. This is coverage selection, not a ranking of training value.

| Distribution | Before | After |
| --- | --- | --- |
| k | {before['k']} | {after['k']} |
| proposal/response | {before['decision_kinds']} | {after['decision_kinds']} |
| seats by player count | {before['ego_by_players']} | {after['ego_by_players']} |

All 30 two-player/two-round parents retain k=2 and k=3. Parent composition remains
30 two-player/two-round, 20 two-player/one-round, 50 three-player/one-round.
No three-player multi-round parent or measured S>.05 candidate has been added.
Scarce categories cannot be made equally frequent without creating new candidates.

Every selected row is identical to its source record, including C/S, posterior,
reference and split. All 100 parent/reference records and reference files match.
Original independent audits are retained in `provenance/source_verification/`;
`audit.json` verifies subset inheritance, not a new solver/C/S run. Parent-level
`entrance_selection` fields describe original generation; current selection is in
`selection_ledger.jsonl`. Full counts and policy are in `balance.json`.

Reproduce into a new directory:

```sh
python -m examples.strategic_slices.rebalance_candidates --source {source} --output NEW_DIRECTORY
```
'''
    (out/'REPORT.md').write_text(report)
    manifest['files'] = {str(f.relative_to(out)): file_hash(f) for f in out.rglob('*') if f.is_file()}
    write_json(out/'manifest.json', manifest)
    TerminalCandidates(out)
    assert file_hash(source/'manifest.json') == source_hash
    write_json(out/'CANDIDATES_VERIFIED.json', dict(manifest_sha256=file_hash(out/'manifest.json'),
        audit_mode=audit['mode'], D_measured=False, final_100_slices_selected=False))
    print(json.dumps(dict(before=before, after=after), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path('new/local_data/strategic_slices_oracle_consistent_candidates_v1'))
    parser.add_argument('--output', type=Path, default=Path('new/local_data/strategic_slices_oracle_consistent_candidates_v2'))
    args = parser.parse_args()
    package(args.source, args.output)
