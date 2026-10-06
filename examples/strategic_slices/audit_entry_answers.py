"""Calibrate historical information contrasts and scan the saved terminal pool.

No solver search, model calls, or changes to the existing dataset. Each parent
has a resumable, hash-bound result. All reachable answer groups are measured;
selection weights are the original oracle reach, never a balanced substitute.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess
import time

import numpy as np

from training.strategic_slices.common import file_hash, stable, write_json
from training.strategic_slices.entry_answers import action_information_value, measure_entry_answers
from training.strategic_slices.terminal_candidates import TerminalCandidates


def historical_calibration():
    commit = '86657c9f5dbf826e8a29a4adc7d567fa0771fb02'
    root = 'examples/social_mixed/paired_bank_v2/'
    def read(name):
        return subprocess.check_output(['git', 'show', commit+':'+root+name])
    manifest = json.loads(read('manifest.json'))
    import hashlib
    assert hashlib.sha256(read('manifest.json')).hexdigest() == 'e53ff4b4b9e9e2050a701e97f24f165bfef0b2b9200e7e1f611b688f8394732b'
    payloads = {name: read(name) for name in ('cases.jsonl', 'tasks.jsonl', 'relations.jsonl')}
    for name, payload in payloads.items():
        assert hashlib.sha256(payload).hexdigest() == manifest['files'][name]['sha256']
    cases = {r['canonical_id']: r for r in map(json.loads, payloads['cases.jsonl'].splitlines())}
    tasks = {r['canonical_id']: r for r in map(json.loads, payloads['tasks.jsonl'].splitlines()) if r['paired_view'] == 'O'}
    rows = []
    for rel in map(json.loads, payloads['relations.jsonl'].splitlines()):
        if rel['relation'] != 'must_change':
            continue
        a, b = [cases[rel[key]] for key in ('left', 'right')]
        ta, tb = [tasks[rel[key]] for key in ('left', 'right')]
        ego = ta['input']['player']
        assert ta['input']['legal_actions'] == tb['input']['legal_actions']
        qa, qb = [np.array(x['labels']['action_values'])[:, ego] for x in (a, b)]
        # Verify the fixed world-by-action continuation itself, not just metadata.
        tables = [{stable(w): np.asarray(x['labels']['per_world_payoffs'])[:, j, :]
                   for j, w in enumerate(x['labels']['worlds'])} for x in (a, b)]
        assert tables[0].keys() == tables[1].keys()
        assert all(np.allclose(tables[0][w], tables[1][w], atol=1e-9, rtol=0) for w in tables[0])
        metric = action_information_value([qa, qb], [.5, .5])
        assert metric['must_change_pairs'] == [[0, 1]]
        rows.append(dict(left=rel['left'], right=rel['right'], split=rel['split'],
            differing_input_fields=sorted(k for k in set(ta['input']) | set(tb['input'])
                if ta['input'].get(k) != tb['input'].get(k)), **metric))
    return dict(source_commit=commit, counts=dict(Counter(r['split'] for r in rows)),
        scope='Balanced two-condition diagnostic only. Old cases do not supply a common native oracle-reach distribution; this is NOT current-dataset S or a free-query value.',
        rows=rows, minimum_balanced_value=min(r['S'] for r in rows),
        maximum_balanced_value=max(r['S'] for r in rows))


def run(source, out, limit=None):
    out.mkdir(parents=True, exist_ok=True)
    data = TerminalCandidates(source)
    identity = dict(source_manifest_sha256=file_hash(source/'manifest.json'),
        implementation_sha256=file_hash(Path('training/strategic_slices/entry_answers.py')),
        audit_script_sha256=file_hash(Path(__file__)))
    config = out/'config.json'
    if config.exists() and json.loads(config.read_text()) != identity:
        raise ValueError('Audit source changed; use a new output directory')
    write_json(config, identity)
    write_json(out/'historical_calibration.json', historical_calibration())
    selected = {r['id'] for r in data.candidates}
    candidates = {r['parent_id']: r for r in data.candidates}
    results = []
    for pid in sorted(data.parents)[:limit]:
        path = out/(pid+'.json')
        if path.exists():
            result = json.loads(path.read_text())
        else:
            start = time.monotonic()
            tree = data.reference(candidates[pid])
            groups = measure_entry_answers(tree, pid)
            for group in groups:
                group['split'] = data.parents[pid]['split']
                group['selected_member_ids'] = [m['candidate_id'] for m in group['members'] if m['candidate_id'] in selected]
            result = dict(parent_id=pid, reference_id=candidates[pid]['reference_id'],
                policy_sha256=tree.certificate['policy_sha256'], nodes=len(tree.entries),
                groups=groups, seconds=time.monotonic()-start)
            temp = path.with_suffix('.tmp')
            write_json(temp, result)
            temp.replace(path)
        results.append(result)
        print(pid, 'groups', len(result['groups']), 'max_S', max((g['S'] for g in result['groups']), default=0), flush=True)
        groups = [g for r in results for g in r['groups']]
        positive = [g for g in groups if g['S'] > .05]
        write_json(out/'summary.json', dict(**identity, parents=len(results), total_parents=len(data.parents),
            complete=len(results)==len(data.parents), groups=len(groups),
            positive_groups=len(positive), positive_parents=len({g['parent_id'] for g in positive}),
            must_change_groups=sum(bool(g['must_change_pairs']) for g in groups),
            maximum_S=max((g['S'] for g in groups), default=0),
            positive_group_ids=[g['id'] for g in positive],
            positive_members_already_selected=sum(len(g['selected_member_ids']) for g in positive),
            new_oracle_solves=0, model_calls=0,
            scope='S is conditional collective value of an existing private answer during one focal decision; oracle reach and terminal continuation unchanged. Never assign group S to individual members.'))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, default=Path('new/local_data/strategic_slices_oracle_consistent_candidates_v2'))
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--limit', type=int)
    args = p.parse_args()
    run(args.source, args.output, args.limit)
