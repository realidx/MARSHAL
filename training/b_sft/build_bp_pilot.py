"""Generate legal small-game B/P lessons, verify labels, and split game families.

Teaching only: this module never changes the outcome self-play generator.
"""
import argparse
from collections import Counter, defaultdict
from copy import copy, deepcopy
import hashlib
from itertools import permutations, product
import json
from pathlib import Path
import random

import numpy as np

from training.b_sft.prepare_no_catalogue_probe import expand_support, view
from training.b_sft.social_private_teacher import PrivateEpisode, audit_native
from training.b_sft.social_bp_curriculum import acceptable, digest
from training.b_sft.social_b_oracle import NAMES
from training.b_sft.shared_teacher import SearchLimit
from training.b_sft.social_bp_training import VERSION, native_completion, reward, select_batch


def topology(raw):
    """Canonical under player/commitment/goal renaming; round variants stay together."""
    game = raw['game']; n = game['n_players']; counts = game['n_actions_per_player']; reps = []
    for players in permutations(range(n)):
        for maps in product(*(tuple(permutations(range(c))) for c in counts)):
            goals = sorted(tuple(sorted((players[a['player_id']], maps[a['player_id']][a['action_id']])
                                       for a in g['required_actions'])) for g in game['goals'])
            ordered_counts = [0]*n
            for p in range(n): ordered_counts[players[p]] = counts[p]
            reps.append(json.dumps([ordered_counts, goals], separators=(',', ':')))
    return hashlib.sha256(min(reps).encode()).hexdigest()[:16]


def split_for(family):
    bucket = int(hashlib.sha256(('bp-split:'+family).encode()).hexdigest()[:8], 16) % 8
    return 'validation' if bucket == 0 else 'test' if bucket == 1 else 'train'


def raw_fixture(seed):
    rng = random.Random(seed)
    level = seed % 3
    n = 3 if level == 2 else 2
    counts = [2, 2] + ([1] if n == 3 else [])
    if level == 1 and seed % 2: counts[0] = 3
    g = rng.choice([2, 3]) if level == 0 else rng.choice([3, 4])
    # All goals require a commitment from both focal players. Third-party
    # prerequisites may already hold in an imposed starting state.
    goals = []
    for q in range(g):
        refs = [dict(player_id=p, action_id=rng.randrange(counts[p])) for p in (0, 1)]
        if n == 3 and rng.random() < .6: refs.append(dict(player_id=2, action_id=0))
        goals.append(dict(goal_id=q, binary=True, required_actions=refs))
    own = [rng.choice([1, 1, 0, -1]) for _ in range(g)]; own[rng.randrange(g)] = 1
    partner = [rng.choice([1, 0, -1]) for _ in range(g)]; partner[-1] = 1
    hidden = [0, 1] if level == 2 and g >= 3 and seed % 2 else [0]
    rows = []
    for values in product((1, 0, -1), repeat=len(hidden)):
        row = partner.copy()
        for q, v in zip(hidden, values): row[q] = v
        rows.append(row)
    types = {'0': [own], '1': rows}
    if n == 3: types['2'] = [[rng.choice([1, 1, 0]) for _ in range(g)]]; types['2'][0][-1] = 1
    if level == 2 and seed % 4 == 2:
        own[0] = 1
        types['0'] = [own[:-1]+[v] for v in (1, 0, -1)]
    raw = dict(id=f'pilot-short-{seed}', ego=0, own_preferences=own, history=[], type_catalogues=types,
        game=dict(n_players=n, n_actions_per_player=counts, max_changes=1, menu_enabled=False,
                  round_robin=list(range(n)), goals=goals))
    order = list(range(g)); rng.shuffle(order)
    raw['game']['goals'] = [dict(goals[old], goal_id=new) for new, old in enumerate(order)]
    raw['own_preferences'] = [own[i] for i in order]
    raw['type_catalogues'] = {p: [[row[i] for i in order] for row in rows] for p, rows in types.items()}
    raw['teaching_query_goal'] = order.index(0)
    return raw, level


def final_setup(raw, actor, *, private=False):
    raw = deepcopy(raw); n = raw['game']['n_players']
    order = [p for p in range(n) if p != actor]+[actor]
    raw['game']['round_robin'] = order*(2 if private else 1)
    setup = []
    # A third party commits its prerequisite in the imposed setup. This is a
    # legal OFFER/ACCEPT, never a synthetic state mutation or behavior evidence.
    for p in order[:-1]:
        if p == 2:
            setup += [dict(action='OFFER', partner_id=0, proposer_action=[1], partner_action=[0]*raw['game']['n_actions_per_player'][0]), dict(response='ACCEPT')]
        else: setup.append(dict(action='PASS'))
    if private:
        setup += [dict(action='INVESTIGATE', player=1, goal=raw.get('teaching_query_goal', 0))]
        setup += [dict(action='PASS') for _ in order[:-1]]
    return raw, setup


def make_task(e, public, setup, events, kind, stage, family, *, q=(1, 0), facts=(), previous=None, new_count=1, pool=None, source=''):
    own = e.raw['own_preferences']; inp = view(e, public, 0, own, facts, setup, events)
    teacher = dict(policy_sha256=e.tree.certificate['policy_sha256'], native=audit_native(e.tree))
    direct = False
    if kind == 'B':
        b = e.belief(*q, observer=0, own=own, private_results=facts)
        gold = {k: b[k] for k in ('possible_preferences', 'favored')}
        skill = 'formation' if previous is None else 'maintain' if previous == gold else 'update'
        inp.update(task=skill, queries=[dict(player=q[0], goal=q[1])])
        if previous is not None:
            inp['previous_belief'] = previous
            if facts: inp['new_evidence'] = 'Your investigation has just delivered the true private answer listed above.'
            else: inp.update(old_history=events[:-new_count], new_history=events[-new_count:])
        teacher.update(gold=gold, preference_weights=b['preference_weights'])
        direct = any((p, g) == q for p, g, v in facts)
        pool = skill
    else:
        choices = e.choices(own, facts); weights = e._weights(0, own, facts)
        known = []; unknown = []
        for p in range(e.rules.spec.n_players):
            for g in range(len(e.rules.spec.goals)):
                values = {w[p][g] for w, weight in zip(e.tree.worlds, weights) if weight > 0}
                if len(values) == 1: known.append(dict(player=p, goal=g, preference=NAMES[next(iter(values))]))
                else: unknown.append(dict(player=p, goal=g))
        if events and unknown:
            prior_weights = e.tree.world_weights*np.array([w[0] == tuple(own) and all(w[p][g] == v for p, g, v in facts) for w in e.tree.worlds])
            prior_weights /= prior_weights.sum()
            if not np.allclose(weights, prior_weights, atol=1e-9, rtol=0):
                raise ValueError('P requires a directly expressible current belief')
        inp.update(legal_actions=choices['actions'], supplied_belief=dict(known_preferences=known,
            unresolved_preferences=unknown, support=(
                'Your CURRENT belief is the stated preference-generation distribution conditioned on these known preferences. There are no additional behavioral likelihood updates in this P exercise.'
                if unknown else 'These known facts completely specify YOUR current belief.')))
        accepted = acceptable(choices['values'], 0)
        if not accepted or len(accepted) == len(choices['actions']): return None
        teacher.update(acceptable_actions=[choices['actions'][i] for i in accepted], action_values=choices['values'])
        skill = pool
    t = dict(task=kind, skill=skill, pool=pool, stage=stage, input=inp, teacher=teacher,
        family=family, split=split_for(family), source=source, direct_answer=direct, training_ready=True,
        mechanism=VERSION, output_arm='action_tools', name_variant=int(family[-1], 16)%2, short_teaching=False)
    t['contrast_group'] = digest((family, source.split(':')[0], kind, pool, stage))
    t['answer_signature'] = json.dumps(teacher.get('gold', teacher.get('acceptable_actions')), sort_keys=True)
    t['id'] = digest((VERSION, kind, pool, inp)); t['native_task_id'] = t['id']
    assert reward(t, native_completion(t))['reward'] == 1
    return t


def lessons(raw, stage):
    raw, public, _ = expand_support(raw); family = topology(raw)
    goal = raw.get('teaching_query_goal', 0); query = (1, goal)
    # Last proposer chooses between real offers. Record every on-policy action
    # then the responder's action, using the same frozen teacher throughout.
    r, setup = final_setup(raw, 1); e = PrivateEpisode(r, setup)
    prior = e.belief(*query, observer=0, own=r['own_preferences'])
    prior = {k: prior[k] for k in ('possible_preferences', 'favored')}
    for action in e.tree.entries[0].actions:
        if action.to_dict().get('action') != 'OFFER': continue
        branch = copy(e)
        try: branch.observe(action.to_dict())
        except ValueError: continue
        events = [action.to_dict()]
        for previous in (None, prior):
            yield make_task(branch, public, setup, events, 'B', stage, family, q=query, previous=previous, source=r['id'])
        old = branch.belief(*query, observer=0, own=r['own_preferences'])
        old = {k: old[k] for k in prior}
        for response in branch.tree.entries[branch.index].actions:
            after = copy(branch)
            try: after.observe(response.to_dict())
            except ValueError: continue
            yield make_task(after, public, setup, events+[response.to_dict()], 'B', stage, family, q=query, previous=old, source=r['id'])
    # Direct final response is a simpler behavior bridge than proposal search.
    r, setup = final_setup(raw, 0); root = PrivateEpisode(r, setup)
    for offer in root.tree.entries[0].actions:
        a = offer.to_dict()
        if a.get('action') != 'OFFER' or a.get('partner_id') != 1: continue
        forced = setup+[a]; e = PrivateEpisode(r, forced)
        before = e.belief(*query, observer=0, own=r['own_preferences'])
        before = {k: before[k] for k in ('possible_preferences', 'favored')}
        for response in e.tree.entries[0].actions:
            branch = copy(e)
            try: branch.observe(response.to_dict())
            except ValueError: continue
            for previous in (None, before):
                yield make_task(branch, public, forced, [response.to_dict()], 'B', stage, family, q=query, previous=previous, source=r['id'])
    yield make_task(root, public, setup, [], 'P', stage, family, pool='uncertain', source=r['id'])
    # Complete information variants and private result-use are not counted as
    # new game families. Constant slots become explicitly public facts.
    for value in (1, 0, -1):
        full = deepcopy(raw)
        compatible = [row for row in full['type_catalogues']['1'] if row[goal] == value]
        if not compatible: continue
        full['type_catalogues']['1'] = [compatible[0]]
        full, fp, _ = expand_support(full); fr, fs = final_setup(full, 0)
        fe = PrivateEpisode(fr, fs)
        yield make_task(fe, fp, fs, [], 'P', stage, family, pool='complete', source=r['id'])
        pr, ps = final_setup(raw, 0, private=True); pe = PrivateEpisode(pr, ps); facts = [(1, goal, value)]
        yield make_task(pe, public, ps, [], 'P', stage, family, facts=facts, pool='result_use', source=r['id'])
        # A B update asks immediately after delivery, not after the intervening
        # passes used by the P result-use exercise. No delayed revelation rule.
        br = deepcopy(raw); bs = []
        br['game']['round_robin'] = [p for p in range(br['game']['n_players']) if p not in (0,1)]+[0,1]
        if br['game']['n_players'] == 3:
            bs += [dict(action='OFFER', partner_id=0, proposer_action=[1], partner_action=[0]*br['game']['n_actions_per_player'][0]), dict(response='ACCEPT')]
        bs += [dict(action='INVESTIGATE', player=1, goal=goal)]
        be = PrivateEpisode(br, bs)
        yield make_task(be, public, bs, [], 'B', stage, family, q=query, facts=facts, previous=prior, source=r['id'])


def quotas(split):
    factor = 1 if split == 'train' else .25
    totals = dict(formation=48, maintain=32, update=48, complete=32, uncertain=32, result_use=32, information=32)
    result = {}
    for pool, count in totals.items():
        total = int(count*factor)
        # Keep at least two examples in each validation difficulty/ability cell.
        hard = max(2, total//8); middle = max(2, total*3//8)
        for level, num in enumerate((total-middle-hard, middle, hard)): result[pool, level] = num
    return result


def positive_quota(count, split, stage):
    return (count+1)//2 if split != 'train' and stage == 1 else count//2


def favored_update(t):
    old = t['input'].get('previous_belief'); gold = t['teacher'].get('gold')
    return bool(old and gold and old['possible_preferences'] == gold['possible_preferences'] and old['favored'] != gold['favored'])


def nonredundant_favored(t):
    gold = t['teacher'].get('gold', {})
    return len(gold.get('possible_preferences', [])) > 1 and gold.get('favored') != 'undetermined'


def choose(pool, limit, *, seed):
    rng = random.Random(seed); groups = defaultdict(list)
    for t in pool: groups[t['contrast_group']].append(t)
    keys = list(groups); rng.shuffle(keys); result = []
    # Select contrasting answers from one family before another family, while
    # preventing a large family from filling the entire cell.
    while len(result) < limit and keys:
        remaining = []
        for key in keys:
            choices = groups[key]
            if not choices: continue
            signatures = defaultdict(list)
            for t in choices: signatures[t['answer_signature']].append(t)
            labels = list(signatures); rng.shuffle(labels)
            for signature in labels[:2]:
                t = rng.choice(signatures[signature]); result.append(t); choices.remove(t)
                if len(result) == limit: break
            if choices: remaining.append(key)
            if len(result) == limit: break
        keys = remaining
    return result


def write_dataset(tasks, out, failures):
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    from training.b_sft.bp_semantics import semantic_id
    by_id = {t['id']: t for t in tasks if t is not None}
    semantic = {}
    for t in by_id.values():
        key = semantic_id(t)
        t['semantic_id'] = key
        if key not in semantic or t['stage'] < semantic[key]['stage']: semantic[key] = t
    # Direct truth-reading is an interface check, not behavioral B training.
    # Keep those records reviewable without using them to fill update quotas.
    direct_checks = [t for t in semantic.values() if t['task'] == 'B' and t.get('direct_answer')]
    unique = {t['id']: t for t in semantic.values() if not (t['task'] == 'B' and t.get('direct_answer'))}
    # Stratify by structural coverage, using no model performance. Pure hashing
    # can accidentally put every easy topology outside validation.
    available_cells = {(t['pool'], t['stage']) for t in unique.values()}
    development_path = Path(__file__).resolve().parents[2]/'examples/social_bp/development_families.json'
    development_families = set(json.loads(development_path.read_text())['families'])
    family_counts = defaultdict(Counter)
    for t in unique.values():
        fc = family_counts[t['family']]; fc[t['pool'], t['stage']] += 1
        if t['pool'] == 'information':
            fc['positive', t['stage']] += bool(t.get('information_positive'))
            fc['own_information', -1] += bool(t.get('information_positive') and t['teacher'].get('own_query_margin', 0) > .10000001)
            fc['future_negative', -1] += t.get('information_negative_kind') == 'future_opportunity_remains'
        fc['favored_update', -1] += favored_update(t)
        fc['nonredundant_favored', -1] += nonredundant_favored(t)
    required = [key for key in ('favored_update', 'nonredundant_favored', 'own_information', 'future_negative')
                if sum(fc[key, -1] for fc in family_counts.values())]
    for salt in range(100000):
        assignment = {}
        counts = Counter()
        for f, fc in family_counts.items():
            bucket = int(hashlib.sha256(f'{salt}:{f}'.encode()).hexdigest()[:8], 16) % 8
            assignment[f] = 'train' if f in development_families else 'validation' if bucket == 0 else 'test' if bucket == 1 else 'train'
            for (pool, stage), count in fc.items(): counts[assignment[f], pool, stage] += count
        if all(counts[split, pool, stage] >= count for split in ('train', 'validation', 'test')
               for (pool, stage), count in quotas(split).items() if (pool, stage) in available_cells) and all(
                   counts[split, 'positive', stage] >= positive_quota(count, split, stage)
                   for split in ('train','validation','test') for (pool, stage), count in quotas(split).items()
                   if pool == 'information' and (pool, stage) in available_cells) and all(
                       counts[split, key, -1] > 0 for split in ('train', 'validation', 'test') for key in required): break
    else: raise ValueError('No family-disjoint split covers every available ability/difficulty cell')
    for t in unique.values(): t['split'] = assignment[t['family']]
    selected = []; gaps = {}
    for split in ('train', 'validation', 'test'):
        for (pool, stage), count in quotas(split).items():
            candidates = [t for t in unique.values() if (t['split'], t['pool'], t['stage']) == (split, pool, stage)]
            # Reserve actual behavioral updates; direct facts never fill gaps.
            if pool == 'update':
                behavioral = [t for t in candidates if not t['direct_answer']]
                reserved = choose([t for t in behavioral if favored_update(t)], min(2, count), seed=f'{split}:{stage}:favored')
                picked = reserved + choose([t for t in behavioral if t not in reserved], count-len(reserved), seed=f'{split}:{pool}:{stage}')
            elif pool == 'information':
                pc = positive_quota(count, split, stage)
                positive = choose([t for t in candidates if t.get('information_positive')], pc, seed=f'{split}:{stage}:positive')
                own_positive = [t for t in candidates if t.get('information_positive') and t['teacher'].get('own_query_margin', 0) > .10000001]
                if positive and own_positive and not any(t in own_positive for t in positive):
                    positive[-1] = choose(own_positive, 1, seed=f'{split}:{stage}:own-information')[0]
                negatives = [t for t in candidates if not t.get('information_positive')]
                future = choose([t for t in negatives if t.get('information_negative_kind') == 'future_opportunity_remains'],
                                min(2, count-pc), seed=f'{split}:{stage}:future')
                remaining = [t for t in negatives if t not in future]
                matching = [t for t in remaining if any(t['contrast_group'] == p['contrast_group'] for p in positive)]
                chosen = choose(matching, count-pc-len(future), seed=f'{split}:{stage}:matched')
                if len(chosen)+len(future) < count-pc:
                    chosen += choose([t for t in remaining if t not in chosen], count-pc-len(future)-len(chosen), seed=f'{split}:{stage}:other')
                picked = positive+future+chosen
            elif pool == 'uncertain':
                qual = [t for t in candidates if t.get('qualitative_level')]
                plain = [t for t in candidates if not t.get('qualitative_level')]
                qc = min(count//2, len(qual))
                picked = choose(qual, qc, seed=f'{split}:{stage}:qual')+choose(plain, count-qc, seed=f'{split}:{stage}:plain')
            else:
                reserved = choose([t for t in candidates if nonredundant_favored(t)], min(2, count), seed=f'{split}:{stage}:favored')
                picked = reserved + choose([t for t in candidates if t not in reserved], count-len(reserved), seed=f'{split}:{pool}:{stage}')
            if len(picked) < count: gaps[f'{split}/{pool}/{stage}'] = dict(needed=count, available=len(picked))
            selected.extend(picked)
    (out/'candidate_tasks.jsonl').write_text(''.join(json.dumps(t)+'\n' for t in unique.values()))
    (out/'direct_reading_checks.jsonl').write_text(''.join(json.dumps(t)+'\n' for t in direct_checks))
    (out/'generation_failures.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in failures))
    summary = dict(version=VERSION, candidates=len(unique), selected=len(selected), gaps=gaps,
                   splits=dict(Counter(t['split'] for t in selected)), training_ready=not gaps, split_salt=salt)
    summary['direct_reading_checks_excluded'] = len(direct_checks)
    summary['information_positives'] = dict(Counter(t['split'] for t in selected if t.get('information_positive')))
    summary['information_future_negatives'] = dict(Counter(t['split'] for t in selected if t.get('information_negative_kind') == 'future_opportunity_remains'))
    summary['favored_only_updates'] = dict(Counter(t['split'] for t in selected if favored_update(t)))
    summary['nonredundant_favored'] = dict(Counter(t['split'] for t in selected if nonredundant_favored(t)))
    summary['own_information_positives'] = dict(Counter(t['split'] for t in selected if t.get('information_positive') and t['teacher'].get('own_query_margin', 0) > .10000001))
    summary['development_families_train_only'] = sorted(development_families)
    if not gaps:
        train = [t for t in selected if t['split'] == 'train']
        for step in range(100):
            select_batch(train, step, 100, 16, 20260914, dict(allowed={'B': 2, 'P': 2}))
        for split in ('train', 'validation', 'test'):
            rows = [t for t in selected if t['split'] == split]
            (out/(split+'_tasks.jsonl')).write_text(''.join(json.dumps(t)+'\n' for t in rows))
        (out/'tasks.jsonl').write_text(''.join(json.dumps(t)+'\n' for t in selected))
    (out/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    return summary


def main():
    p = argparse.ArgumentParser(); p.add_argument('--out', required=True); p.add_argument('--seeds', type=int, default=500)
    p.add_argument('--extra-tasks'); a = p.parse_args(); tasks = []; failures = []
    for seed in range(a.seeds):
        try:
            raw, stage = raw_fixture(seed)
            tasks.extend(t for t in lessons(raw, stage) if t is not None)
        except (SearchLimit, ValueError) as exc: failures.append(dict(seed=seed, reason=str(exc)))
        if seed % 50 == 0: print(json.dumps(dict(seed=seed, tasks=len(tasks), failures=len(failures))), flush=True)
    if a.extra_tasks: tasks.extend(json.loads(s) for s in Path(a.extra_tasks).read_text().splitlines())
    print(json.dumps(write_dataset(tasks, a.out, failures), indent=2))


if __name__ == '__main__': main()
