"""Offline union and full-window diagnostics of frozen terminal-D evidence.

No new model calls, equilibrium solving, or mutation of source result records.
Decision gaps condition on visible information and fixed-reference action reach;
controlled actions are interventions, never evidence about the hidden world.
"""
import ast
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import tarfile

import numpy as np
from new.benac_slice_pilot.metrics import _groups
from training.b_sft.social_private_teacher import observed_slots
from .common import digest, file_hash, seed_for, stable, write_json, write_rows
from .freeze import atomic_json
from .terminal_d import TerminalRollout, summarize_slice
from .values import extreme_value

EPS = 1e-7


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_archive(folder, archive_name, prefix):
    folder = Path(folder)
    manifest = json.loads((folder/'ARCHIVE_MANIFEST.json').read_text())
    archive = folder/archive_name
    require(file_hash(archive) == manifest['archive_sha256'], 'Archive checksum mismatch')
    expected = ({f'{run}/{name}': sha for run, files in manifest['runs'].items()
                 for name, sha in files.items()} if 'runs' in manifest else
                {f'{prefix}/{name}': sha for name, sha in manifest['files'].items()})
    found, retained = set(), {}
    # Verify every archived file but retain only evaluation evidence, not HTTP logs.
    with tarfile.open(archive) as handle:
        for member in handle:
            if not member.isfile():
                continue
            require(member.name not in found, 'Duplicate archive member')
            payload = handle.extractfile(member).read()
            require(hashlib.sha256(payload).hexdigest() == expected.get(member.name),
                    'Archive member checksum mismatch: '+member.name)
            found.add(member.name)
            if member.name.startswith(prefix+'/evaluation/'):
                retained[member.name[len(prefix+'/evaluation/'):]] = payload
    require(found == set(expected), 'Missing archived files')
    complete = json.loads(retained['COMPLETE.json'])
    for name, sha in complete['files'].items():
        require(hashlib.sha256(retained[name]).hexdigest() == sha, 'Completion checksum mismatch: '+name)
    protocol = json.loads(retained['protocol.json'])
    for name, sha in protocol['source_identity'].items():
        require(hashlib.sha256(retained['source/'+name]).hexdigest() == sha, 'Source snapshot mismatch')
    for name in ('slices.jsonl', 'summary.json'):
        require((folder/name).read_bytes() == retained[name], 'Published summary differs from archive')
    parents = {}
    migration = json.loads(retained['EXECUTION_MIGRATION.json']) if 'EXECUTION_MIGRATION.json' in retained else None
    if migration:
        require(migration['new_protocol_sha256'] == digest(protocol), 'Migration destination mismatch')
        require(migration['old_protocol_sha256'] == digest(migration['old_protocol']), 'Migration source mismatch')
    for name, payload in retained.items():
        if not name.startswith('parents/'):
            continue
        record = json.loads(payload)
        result = record['result']
        require(record['sha256'] == digest(result), 'Parent result checksum mismatch')
        inherited = result['protocol_sha256'] != digest(protocol)
        if inherited:
            require(migration is not None and result['protocol_sha256'] == migration['old_protocol_sha256']
                    and migration['inherited_parents'].get(Path(name).name) == hashlib.sha256(payload).hexdigest(),
                    'Unverified inherited result')
        parents[result['parent_id']] = dict(result=result, member=f'{prefix}/evaluation/{name}',
            member_sha256=hashlib.sha256(payload).hexdigest(),
            execution_protocol=(migration['old_protocol'] if inherited else protocol))
    return dict(archive=str(archive), archive_sha256=manifest['archive_sha256'],
                verified_files=len(found), protocol=protocol, parents=parents, evidence=retained)


def function_ast(payload, name):
    node = next(n for n in ast.parse(payload).body if getattr(n, 'name', None) == name)
    return ast.dump(node, include_attributes=False)


def compatible_runs(old, new):
    a, b = old['protocol'], new['protocol']
    for key in ('checkpoint_sha256', 'runtime_versions'):
        require(a['model_identity'][key] == b['model_identity'][key], 'Model/runtime differs: '+key)
    for key in ('model', 'replicas', 'seed', 'temperature', 'top_p', 'top_k', 'repetition_penalty',
                'max_tokens', 'context', 'dtype', 'tensor_parallel_size', 'tool_call_parser'):
        require(a['config'][key] == b['config'][key], 'Sampling/serving differs: '+key)
    # New validation/packaging code is allowed; prompt, RNG and rollout semantics must match.
    for module, names in [('terminal_d', ['TerminalRollout', 'summarize_slice']),
                          ('common', ['request', 'decode', 'seed_for'])]:
        for name in names:
            path = 'source/training/strategic_slices/'+module+'.py'
            require(function_ast(old['evidence'][path], name) == function_ast(new['evidence'][path], name),
                    'Measurement semantics changed: '+name)


def merge_evidence(dataset, previous, old, new, output):
    compatible_runs(old, new)
    reuse = json.loads((dataset.root/'D_reuse.json').read_text())
    require(old['protocol']['dataset_sha256'] == file_hash(previous.root/'manifest.json') == reuse['source_v2_manifest_sha256'], 'Old dataset identity mismatch')
    require(new['protocol']['dataset_sha256'] == file_hash(dataset.root/'manifest.json'), 'New dataset identity mismatch')
    reusable, changed = set(reuse['reuse_eligible_candidate_ids']), set(reuse['requires_new_D'])
    require(not reusable & changed and reusable | changed == {r['id'] for r in dataset.candidates}, 'Reuse partition mismatch')
    require(sorted(changed) == new['protocol']['candidate_subset_ids'], 'Delta question list mismatch')
    before = {r['id']:r for r in previous.candidates}
    grouped, provenance, summaries = defaultdict(list), [], []
    for row in dataset.candidates:
        inherited = row['id'] in reusable
        source = old if inherited else new
        if inherited:
            require(row == before[row['id']], 'Changed question cannot reuse results')
            rid = row['reference_id']
            require(dataset.references[rid] == previous.references[rid], 'Reference record changed')
            require(file_hash(dataset.root/dataset.references[rid]['file']) == file_hash(previous.root/previous.references[rid]['file']), 'Reference policy changed')
            require(dataset.parents[row['parent_id']]['raw'] == previous.parents[row['parent_id']]['raw'], 'Parent game changed')
        parent = source['parents'][row['parent_id']]
        games = [g for g in parent['result']['games'] if g['slice_id'] == row['id']]
        require(len(games) == 8 and {g['replica'] for g in games} == set(range(8)), 'Missing/repeated replicas')
        for g in games:
            require(g['seed'] == seed_for(42, 'terminal-D', row['id'], g['replica']), 'Replica seed mismatch')
            require(g['parent_id'] == row['parent_id'], 'Trajectory parent mismatch')
        summary = summarize_slice(row, games, 42)
        saved = next(r for r in parent['result']['slices'] if r['slice_id'] == row['id'])
        require(summary == saved, 'Recomputed slice summary differs')
        summaries.append(summary)
        grouped[row['parent_id']].extend(games)
        provenance.append(dict(slice_id=row['id'], source='v2_reused' if inherited else 'v4_delta',
            archive=source['archive'], archive_sha256=source['archive_sha256'],
            member=parent['member'], member_sha256=parent['member_sha256'],
            execution_protocol_sha256=parent['result']['protocol_sha256'],
            workers=parent['execution_protocol']['config']['workers'],
            scheduler=parent['execution_protocol']['config'].get('scheduler', 'batch'),
            original_game_records_sha256=digest(games)))
    output.mkdir(parents=True, exist_ok=True)
    write_rows(output/'merged_slices.jsonl', summaries)
    write_rows(output/'provenance.jsonl', provenance)
    write_json(output/'MERGE.json', dict(dataset_sha256=file_hash(dataset.root/'manifest.json'),
        old_archive_sha256=old['archive_sha256'], new_archive_sha256=new['archive_sha256'],
        counts=dict(Counter(r['source'] for r in provenance)), candidates=len(summaries),
        trajectories=sum(len(g) for g in grouped.values()),
        original_protocols_preserved=True, model_and_sampling_compatible=True,
        source_result_files_modified=False, new_model_calls=0))
    return grouped, summaries


def visible_posterior(tree, node, ego, reach, world_index):
    """World index selects only the observed information cell, never a point mass."""
    ids = next(ids for ids in _groups(tree, node, ego, None) if world_index in ids)
    weights = np.zeros(tree.w)
    weights[ids] = reach[ids]
    require(weights.sum() > 0, 'Observed information cell has zero reference reach')
    return weights/weights.sum()


def audit_game(tree, row, game, cfg, cache):
    job = TerminalRollout(tree, row, game['replica'], cfg['seed'])
    require(job.world_index == game['world_index'] and job.member_index == game['member_index'], 'Reset mismatch')
    reach = np.asarray(job.member['world_weights'], dtype=float).copy()
    reports, query_slot = [], None
    def q_values(node, weights, remaining):
        key = (row['ego'], node, remaining, tuple(weights))
        if key not in cache:
            cache[key] = extreme_value(tree, row['ego'], node, weights, remaining)['root_Q']
        return np.asarray(cache[key])
    for number, call in enumerate(game['calls']):
        req = job.request(cfg)
        require(req == call['request'], 'Replayed visible request or seed differs')
        require(job.index == call['node'], 'Recorded call node differs')
        weights = visible_posterior(tree, job.index, row['ego'], reach, job.world_index)
        remaining = row['k']-number
        q = np.asarray(job.member['root_Q']) if number == 0 else q_values(job.index, weights, remaining)
        ai = call['action_index']
        valid = call['protocol_status'] == 'ok'
        gap = max(0., float(q.max()-q[ai])) if valid else None
        if number == 0 and valid:
            require(abs(gap-call['first_action_oracle_gap']) < EPS, 'Root gap differs')
        action = tree.entries[job.index].actions[ai].to_dict() if valid else None
        report = dict(decision=number+1, node=job.index, remaining_k=remaining,
            prompt_sha256=call['prompt_sha256'], status=call['protocol_status'],
            action_index=ai, action=action, Q=q.tolist(), posterior=weights.tolist(),
            gap=gap, optimal_indices=np.flatnonzero(q.max()-q <= EPS).tolist(),
            after_model_query=query_slot is not None, answer_sensitive=False)
        if query_slot is not None and (row['information_channels'].get('query_answer') or 0) > .05:
            # Compare alternate visible answers at this same public history,
            # holding own type and every other private answer fixed.
            world = tree.worlds[job.world_index]
            slots = observed_slots(tree.entries[job.index].node, row['ego'])
            cells = defaultdict(list)
            for wi, alternative in enumerate(tree.worlds):
                if (alternative[row['ego']] == world[row['ego']] and all(
                        alternative[p][g] == world[p][g] for p,g in slots if (p,g) != query_slot)
                        and reach[wi] > 0):
                    cells[alternative[query_slot[0]][query_slot[1]]].append(wi)
            alternatives = []
            for answer, ids in sorted(cells.items()):
                w = np.zeros(tree.w); w[ids] = reach[ids]; w /= w.sum()
                aq = q_values(job.index, w, remaining)
                alternatives.append(dict(answer=answer, Q=aq.tolist(),
                    optimal_indices=np.flatnonzero(aq.max()-aq <= EPS).tolist()))
            report['answer_cells'] = alternatives
            report['answer_sensitive'] = any(set(a['optimal_indices']).isdisjoint(b['optimal_indices'])
                for i,a in enumerate(alternatives) for b in alternatives[i+1:])
            report['visible_answer'] = world[query_slot[0]][query_slot[1]]
        reports.append(report)
        if action and action.get('action') == 'INVESTIGATE':
            query_slot = (action['player'], action['goal'])
        step_count = len(job.steps)
        job.accept(call, req)
        for step in job.steps[step_count:]:
            if step['source'] == 'saved-reference':
                reach *= tree.policy[step['node']][step['action_index']]
        require(reach[job.world_index] > 0, 'Realized reference path has zero probability')
    replay = job.record()
    # CPU architectures can sum fractional terminal goal utilities in a
    # different order. Only payoff numbers get tolerance; all actions, calls,
    # resets, statuses and states must still be byte-equivalent JSON values.
    for key in ('utility', 'terminal_utilities'):
        if replay[key] is None or game[key] is None:
            require(replay[key] is None and game[key] is None, 'Native utility presence mismatch')
        else:
            require(np.allclose(replay[key], game[key], atol=1e-12, rtol=0), 'Native utility mismatch')
        replay[key] = game[key]
    require(replay == game, 'Native replay differs from saved trajectory')
    complete = game['status'] == 'terminal'
    return dict(slice_id=row['id'], replica=game['replica'], status=game['status'],
        decisions=reports, decision_gap_sum=sum(r['gap'] for r in reports if r['gap'] is not None) if complete else None,
        valid_prefix_gap_sum=sum(r['gap'] for r in reports if r['gap'] is not None),
        terminal_utility=game['utility'])


def summarize_audit(row, trajectories):
    calls = [c for t in trajectories for c in t['decisions']]
    groups = defaultdict(list)
    for c in calls:
        if c['gap'] is not None:
            groups[c['prompt_sha256']].append(c)
    contrasts = [cs for cs in groups.values() if max(c['gap'] for c in cs)-min(c['gap'] for c in cs) > EPS]
    completed = [t for t in trajectories if t['status'] == 'terminal']
    losses = [t['decision_gap_sum'] for t in completed]
    mixed = 0 < len(completed) < len(trajectories)
    span = max(losses)-min(losses) if losses else None
    sensitive = [c for c in calls if c['answer_sensitive']]
    return dict(slice_id=row['id'], parent_id=row['parent_id'], family=row['family'], split=row['split'],
        k=row['k'], decision_kind=row['decision_kind'], ego=row['ego'],
        strong_acquisition=(row['information_channels'].get('query_answer') or 0) > .05,
        completed=len(completed), mixed_completion=mixed,
        any_step_value_contrast=bool(contrasts), later_step_value_contrast=any(any(c['decision']>1 for c in cs) for cs in contrasts),
        mean_decision_gap_completed=float(np.mean(losses)) if losses else None,
        decision_gap_span_completed=span,
        decision_gap_or_completion_contrast=mixed or bool(span is not None and span > EPS),
        model_query_calls=sum(bool(c['action'] and c['action'].get('action')=='INVESTIGATE') for c in calls),
        after_query_valid_calls=sum(c['after_model_query'] and c['gap'] is not None for c in calls),
        after_query_suboptimal_calls=sum(c['after_model_query'] and c['gap'] is not None and c['gap']>EPS for c in calls),
        answer_sensitive_calls=len(sensitive), answer_sensitive_valid_calls=sum(c['gap'] is not None for c in sensitive),
        answer_sensitive_optimal_calls=sum(c['gap'] is not None and c['gap']<=EPS for c in sensitive),
        answer_sensitive_failed_calls=sum(c['gap'] is None for c in sensitive))
