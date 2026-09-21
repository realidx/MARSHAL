"""Versioned social-reasoning packages. No external evaluation data is read."""
from collections import Counter, defaultdict
from copy import copy, deepcopy
import hashlib
import json
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT/'examples/social_mixed/paired_bank_v2'
VERSION = 'social-reasoning-packages-v4-qualitative-belief'


def stable(x):
    return json.dumps(x, sort_keys=True, separators=(',', ':'))


def sha(x):
    return hashlib.sha256(x).hexdigest()


def replay(task):
    """Recover state-conditioned payoff tables under the declared fixed teacher."""
    from training.b_sft.debug.audit_readable_pretraining import reconstruct
    from training.social_mixed.prepare_distribution_curriculum import root_episode
    i = task['input']; raw, own = reconstruct(i)
    raw['background_prior'] = i['background_prior']
    root, _ = root_episode(stable([raw, i['imposed_setup']]))
    e = copy(root); e.weights = root.weights.copy()
    for a in i['voluntary_history']:
        entry = e.tree.entries[e.index]
        if a.get('action') == 'INVESTIGATE' and entry.actor == i['player']:
            e.index = entry.children[next(j for j, x in enumerate(entry.actions) if x.to_dict() == a)]
        else:
            e.observe(a)
    entry = e.tree.entries[e.index]
    actions = [a.to_dict() for a in entry.actions]
    if actions != i['legal_actions']:
        raise ValueError('Native legal actions changed')
    facts = [(f['player'], f['goal'], {'want': 1, 'neutral': 0, 'avoid': -1}[f['preference']]) for f in i['private_results']]
    weights = e._weights(i['player'], own, facts)
    pay = np.array([e.tree.values[c] for c in entry.children])
    values = np.einsum('awp,w->ap', pay, weights)
    if not np.allclose(values, task['teacher']['action_values'], atol=1e-8, rtol=0):
        raise ValueError('Replayed action values differ from source')
    return e, entry, pay, weights, values


def labels(task):
    from training.b_sft.preference_contract import belief
    e, entry, pay, weights, values = replay(task)
    i = task['input']; actor = i['player']; worlds = np.asarray(e.tree.worlds)
    names = {1: 'want', 0: 'neutral', -1: 'avoid'}
    own = values[:, actor]; optimum = np.flatnonzero(np.isclose(own, own.max(), atol=1e-9, rtol=0)).tolist()
    queries = []
    for p in range(i['game']['n_players']):
        if p == actor:
            continue
        for g in range(len(i['game']['goals'])):
            mass = {name: float(weights[worlds[:, p, g] == val].sum()) for val, name in names.items()}
            branches = []
            for val, name in names.items():
                w = weights * (worlds[:, p, g] == val)
                if w.sum() <= 1e-12:
                    continue
                q = np.einsum('awp,w->ap', pay, w/w.sum())[:, actor]
                branches.append(dict(preference=name, probability=mass[name], action_values=q.tolist(),
                                     optimal_action_indices=np.flatnonzero(np.isclose(q, q.max(), atol=1e-9, rtol=0)).tolist()))
            sets = [set(b['optimal_action_indices']) for b in branches]
            relevant = len(sets) > 1 and any(s != sets[0] for s in sets[1:])
            # Fixed-continuation conditional reweighting: not an executable revelation or VOI.
            queries.append(dict(player=p, goal=g, gold=belief(mass), preference_weights=mass,
                                action_relevant_under_fixed_continuation=relevant,
                                conditional_branches=branches))
    query = max(queries, key=lambda q: (q['action_relevant_under_fixed_continuation'],
                 1-max(q['preference_weights'].values()), -q['player'], -q['goal']))
    transitions = []
    for a, child in zip(entry.actions, entry.children):
        node = e.tree.entries[child].node
        transitions.append(dict(action=a.to_dict(), commitments=[list(x) for x in node.state.snapshot_commitments()],
                                turn_index=node.state.turn_index, terminal=bool(node.state.is_terminal)))
    suboptimal = [own.max()-x for x in own if own.max()-x > 1e-9]
    return dict(action_values=values.tolist(), own_regret=(own.max()-own).tolist(),
                exact_own_optimal_indices=optimum, acceptable_actions=task['teacher']['acceptable_actions'],
                minimum_positive_regret=float(min(suboptimal)) if suboptimal else 0.,
                query=query, query_candidates=queries, immediate_transitions=transitions,
                per_world_payoffs=pay.tolist(), worlds=e.tree.worlds, posterior=weights.tolist(),
                semantic_summary_sufficiency='qualitative support/favored; finite-bank collision check only, not universal sufficiency',
                counterfactual_scope='Conditional reweighting under fixed continuation; not causal revelation or value of information',
                reward_contract='Original teacher acceptable set including response tie convention; exact own optimum separately recorded')


def assign_splits(source, label_info):
    """Move complete validation families; deterministic, no model scores used."""
    from itertools import combinations
    groups = defaultdict(list)
    for t in source:
        if t['split'] == 'validation': groups[t['family']].append(t)
    keys = sorted(groups)
    total = len(source)
    target = round(total * .25)
    original = Counter((t['source_kernel'], t['completion_mode'])
                       for rows in groups.values() for t in rows)
    counts = {k: Counter((t['source_kernel'], t['completion_mode']) for t in groups[k]) for k in keys}
    # Retain action-changing contrasts in validation; this uses teacher labels,
    # never model success/failure or external benchmark scores.
    by_state = defaultdict(list)
    for t in source:
        if t['split'] != 'validation': continue
        i = t['input']
        key = stable([i['game'], i['player'], i['own_preferences'], i['public_preferences'],
                      i['current_state'], i['pending_offer'], i['legal_actions'], i['partner_policy']])
        by_state[key].append(t)
    contrast_families = set()
    for rows in by_state.values():
        for a,b in combinations(rows, 2):
            if set(label_info[a['canonical_id']]['exact_own_optimal_indices']).isdisjoint(
                    label_info[b['canonical_id']]['exact_own_optimal_indices']):
                contrast_families.add(a['family']); contrast_families.add(b['family'])
    relevant = {k: sum(label_info[t['canonical_id']]['query']['action_relevant_under_fixed_continuation']
                       for t in rows) for k,rows in groups.items()}
    original_relevant_fraction = sum(relevant.values()) / sum(original.values())
    best = None
    for n in range(1, len(keys)+1):
        for keep in combinations(keys, n):
            if contrast_families and not contrast_families.intersection(keep): continue
            size = sum(len(groups[k]) for k in keep)
            distance = abs(size-target)
            if best is not None and distance > best[0][0]: continue
            covered = Counter()
            for k in keep: covered.update(counts[k])
            if any(covered[x] < min(2, original[x]) for x in original): continue
            imbalance = sum(abs(covered[x]/size-original[x]/sum(original.values())) for x in original)
            imbalance += abs(sum(relevant[k] for k in keep)/size - original_relevant_fraction)
            score = (distance, imbalance, keep)
            if best is None or score < best[0]: best = (score, set(keep))
    if best is None: raise ValueError('Cannot preserve validation source strata')
    retained = best[1]
    for t in source:
        t['original_split'] = t['split']
        if t['split'] == 'validation' and t['family'] not in retained: t['split'] = 'train'
    return dict(target_train_fraction=.75, unit='source family (includes complete parents)',
                retained_validation_families=sorted(retained),
                moved_to_train_families=sorted(set(keys)-retained),
                selection='Case count, source-kernel/completion-mode and action-relevance balance; retain must-change contrasts; no model outcomes',
                prior_validation_reused=True)


def make_history_free(task, info):
    """Select the history-free model interface; source fields stay for label audit."""
    task['p_information_contract'] = 'current-state-and-correct-qualitative-beliefs-only-v1'
    task['source_input_is_audit_only'] = True
    supplied = dict(known_preferences=[], unresolved_preferences=[],
                    support='Correct current qualitative beliefs',
                    semantic_beliefs=[dict(player=q['player'], goal=q['goal'], **deepcopy(q['gold']))
                                      for q in info['query_candidates']])
    task['input']['supplied_belief'] = supplied
    task['canonical_action_task']['input']['supplied_belief'] = deepcopy(supplied)


def build(cached_labels=None):
    from training.social_mixed.paired_bank import load as source_load, PATH as source_path
    from training.social_mixed.paired_requests import request
    from training.social_mixed.audit_zero_signal import interface_check
    PATH.mkdir(exist_ok=True)
    source = [t for split in ('train', 'validation') for t in source_load(split) if t['paired_view'] == 'O']
    label_info = cached_labels if cached_labels is not None else {t['canonical_id']: labels(t) for t in source}
    split_policy = assign_splits(source, label_info)
    packages = defaultdict(list); cases = []; tasks = []
    for n, original in enumerate(source):
        t = deepcopy(original)
        info = deepcopy(label_info[t['canonical_id']])
        if info['acceptable_actions'] != t['teacher']['acceptable_actions'] or not np.allclose(
                info['action_values'], t['teacher']['action_values'], atol=1e-8, rtol=0):
            raise ValueError('Cached labels disagree with native source teacher')
        parent = t.get('origin_id') or t['canonical_id']
        package = sha(stable([t['family'], parent]).encode())[:24]
        record = dict(canonical_id=t['canonical_id'], package_id=package, split=t['split'],
                      source_task_id=t['source_task_id'], source_kernel=t['source_kernel'],
                      family=t['family'], completion_mode=t['completion_mode'], original_split=t['original_split'], labels=info)
        cases.append(record); packages[package].append(record)
        for view in ('O', 'B', 'Pplus'):
            x = deepcopy(t); x.update(id=t['canonical_id'][:20]+'-'+view, paired_view=view,
                package_id=package, bank_version=VERSION, source_b_query_replaced=True,
                belief_action_relevant=info['query']['action_relevant_under_fixed_continuation'])
            if view == 'B':
                q = info['query']; x.update(task='B', kernel='B1', skill='formation', pool='formation')
                for f in ('previous_belief', 'old_history', 'new_history'):
                    x['input'].pop(f, None)
                x['input']['queries'] = [dict(player=q['player'], goal=q['goal'])]
                x['input']['task'] = 'formation'
                x['teacher'] = dict(gold=q['gold'], preference_weights=q['preference_weights'],
                                    policy_sha256=t['teacher']['policy_sha256'])
            elif view == 'Pplus':
                make_history_free(x, info)
            # Cached builds preserve O/B exactly; recheck the changed P interface.
            if cached_labels is None or view == 'Pplus':
                if not interface_check(x, request_builder=request)['all_passed']:
                    raise ValueError('Paired interface roundtrip failed')
            tasks.append(x)
        if n % 25 == 0:
            print(f'certified {n+1}/{len(source)}', flush=True)
    relations = []
    by_state = defaultdict(list)
    for t, c in zip(source, cases):
        i = t['input']
        key = stable([i['game'], i['player'], i['own_preferences'], i['public_preferences'],
                      i['current_state'], i['pending_offer'], i['legal_actions'], i['partner_policy']])
        by_state[key].append(c)
    for group in by_state.values():
        for j,a in enumerate(group):
            for b in group[j+1:]:
                if a['split'] != b['split']:
                    raise ValueError('Same decision state straddles splits')
                sa=set(a['labels']['exact_own_optimal_indices']); sb=set(b['labels']['exact_own_optimal_indices'])
                relations.append(dict(left=a['canonical_id'], right=b['canonical_id'], split=a['split'],
                    relation='must_change' if sa.isdisjoint(sb) else 'same_optimal_set' if sa==sb else 'overlapping_optima',
                    same_B_query=all(a['labels']['query'][k]==b['labels']['query'][k] for k in ('player','goal')),
                    semantic_B_changed=a['labels']['query']['gold']!=b['labels']['query']['gold'],
                    scope='Same physical decision problem; evidence/prior may differ; not necessarily a single-variable intervention'))
    for rs in packages.values():
        if len({r['split'] for r in rs}) != 1:
            raise ValueError('Parent package straddles splits')
    files={}
    for name, rows in [('tasks.jsonl',tasks),('cases.jsonl',cases),('relations.jsonl',relations)]:
        payload=''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows).encode()
        (PATH/name).write_bytes(payload); files[name]=dict(sha256=sha(payload),rows=len(rows))
    package_rows=[dict(package_id=p,split=rs[0]['split'],canonical_ids=[r['canonical_id'] for r in rs]) for p,rs in sorted(packages.items())]
    payload=(json.dumps(package_rows,indent=2)+'\n').encode();(PATH/'packages.json').write_bytes(payload)
    files['packages.json']=dict(sha256=sha(payload),rows=len(package_rows))
    dependencies=['training/social_mixed/reasoning_bank.py','training/social_mixed/prepare_distribution_curriculum.py',
                  'training/b_sft/social_bp_curriculum.py','training/b_sft/preference_contract.py',
                  'training/social_mixed/paired_requests.py', 'training/social_mixed/history_free_requests.py', 'training/b_sft/social_named_probe.py']
    manifest=dict(version=VERSION,files=files,source_manifest_sha256=sha((source_path/'manifest.json').read_bytes()),
        label_sources={f:sha((ROOT/f).read_bytes()) for f in dependencies},
        counts=dict(Counter(c['split'] for c in cases)), packages=len(packages), split_policy=split_policy,
        action_relevant_queries=dict(Counter(c['split'] for c in cases if c['labels']['query']['action_relevant_under_fixed_continuation'])),
        relations=dict(Counter(r['split']+':'+r['relation'] for r in relations)),
        external_evaluations_used=False, formal_training_ready=False,
        label_build_mode="previously_replayed_labels_reused" if cached_labels is not None else "full_native_replay",
        limitations=['Semantic B is not certified sufficient for every decision.',
          'Matched relations do not certify new structural generalization.',
          'GPU probability, context-length and short learning/retention acceptance still required.'])
    (PATH/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    finalize_metadata()
    print(json.dumps(manifest,indent=2))
    if (PATH/'qualitative_case_audit.jsonl').exists():
        from training.social_mixed.apply_reasoning_policy import apply
        apply()


def finalize_metadata():
    """Pure metadata refinement; does not change replayed values or reward targets."""
    manifest=json.loads((PATH/'manifest.json').read_text())
    tasks=list(map(json.loads,(PATH/'tasks.jsonl').read_text().splitlines()))
    cases={c['canonical_id']:c for c in map(json.loads,(PATH/'cases.jsonl').read_text().splitlines())}
    for t in tasks:
        t['answer_signature']=stable(t['teacher']['gold'] if t['task']=='B' else t['teacher']['acceptable_actions'])
    relations=list(map(json.loads,(PATH/'relations.jsonl').read_text().splitlines()))
    for r in relations:
        tables=[]
        for key in ('left','right'):
            lab=cases[r[key]]['labels'];pay=np.asarray(lab['per_world_payoffs'])
            tables.append({stable(w):pay[:,j,:] for j,w in enumerate(lab['worlds'])})
        a,b=tables
        r['fixed_continuation_payoffs_match']=a.keys()==b.keys() and all(np.allclose(a[w],b[w],atol=1e-9,rtol=0) for w in a)
    for name,rows in [('tasks.jsonl',tasks),('relations.jsonl',relations)]:
        payload=''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows).encode()
        (PATH/name).write_bytes(payload);manifest['files'][name]=dict(sha256=sha(payload),rows=len(rows))
    manifest['label_sources']['training/social_mixed/reasoning_bank.py']=sha(Path(__file__).read_bytes())
    manifest['fixed_payoff_relations']=dict(Counter(r['split']+':'+r['relation'] for r in relations if r['fixed_continuation_payoffs_match']))
    (PATH/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')


def load(split='train', filename='tasks.jsonl'):
    manifest=json.loads((PATH/'manifest.json').read_text())
    if manifest['version'] != VERSION:
        raise ValueError('Reasoning bank version mismatch')
    for name, expected in manifest.get('label_sources',{}).items():
        if sha((ROOT/name).read_bytes())!=expected:raise ValueError('Reasoning label source changed: '+name)
    payload=(PATH/filename).read_bytes()
    if sha(payload) != manifest['files'][filename]['sha256']:
        raise ValueError('Reasoning bank checksum mismatch: '+filename)
    return [r for r in map(json.loads,payload.splitlines()) if r['split']==split]


def panel(count=24):
    """Select whole parent packages without model outcomes, returning all three views."""
    rows=load('validation'); groups=defaultdict(list)
    for t in rows:
        groups[t['package_id']].append(t)
    selected=[]; covered=Counter()
    # Always include complete parent packages for the certified B-to-action anchors.
    anchors={r[k] for r in load('validation','relations.jsonl') if r.get('isolated_B_action_pair') for k in ('left','right')}
    for key in sorted(list(groups)):
        if any(t['canonical_id'] in anchors for t in groups[key]):
            unit=groups.pop(key);selected.extend(unit)
            for t in unit:
                if t['paired_view']=='O':covered[(t['completion_mode'],t['source_kernel'])]+=1
    while groups and len({t['canonical_id'] for t in selected}) < count:
        key=min(groups,key=lambda k:(min(covered[(t['completion_mode'],t['source_kernel'])] for t in groups[k]),k))
        unit=groups.pop(key); selected.extend(unit)
        for t in unit:
            if t['paired_view']=='O': covered[(t['completion_mode'],t['source_kernel'])]+=1
    return sorted(selected,key=lambda t:(t['canonical_id'],t['paired_view']))


if __name__ == '__main__':
    build()
