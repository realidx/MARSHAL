"""Opt-in, dataset-declared practice quotas; no reward or optimizer changes."""
from collections import defaultdict, Counter

VERSION = 'reasoning-v5'
_PLANS = {}


def select(rows, step, seed, validation=False):
    from training.social_mixed.distribution_sampling import select as original
    if validation or not any(t.get('sampling_version') == VERSION for t in rows):
        return original(rows, step, seed, validation)
    from training.social_mixed.distribution_sampling import groups
    key=(seed,tuple((t['id'],t.get('sampling_baseline',False),tuple(sorted(t.get('practice_units',{}).items()))) for t in rows))
    if key not in _PLANS:
        if not all(t.get('sampling_version') == VERSION for t in rows):
            raise ValueError('Partial curriculum metadata')
        baseline=[t for t in rows if t.get('sampling_baseline')]
        if not baseline:raise ValueError('Missing frozen budget baseline')
        units=groups(rows)
        # Every P4 bundle retains full positive/negative control units.
        def controlled(members):
            members=list(members)
            if not any(t['kernel']=='P4' for t in members):return members
            for role in ('query_only','ordinary_only'):
                if not any(t['kernel']=='P4' and t.get('information_role')==role for t in members):
                    options=[(k,v) for k,v in units.items() if k[0]=='P4' and any(t.get('information_role')==role for t in v)]
                    members+=min(options,key=lambda kv:(len(kv[1]),kv[0]))[1]
            return list({t['id']:t for t in members}.values())
        regular={str(k):controlled(v) for k,v in units.items()}
        practice=defaultdict(lambda:defaultdict(list))
        for t in rows:
            for role,unit in t.get('practice_units',{}).items():practice[role][unit].append(t)
        practice={r:{k:controlled(v) for k,v in units.items()} for r,units in practice.items()}
        _PLANS[key]=dict(baseline=baseline,regular=regular,practice=practice,batches=[],counts=Counter())
    plan=_PLANS[key]
    while len(plan['batches'])<=step:
        s=len(plan['batches']);cap=len(original(plan['baseline'],s,seed));chosen={}
        counts=plan['counts']
        def rank(item):
            k,ts=item
            # Shared controls may be frequent; they must not starve the unseen
            # member of a complete contrast bundle.
            return (min(counts[t['id']] for t in ts),sum(counts[t['id']] for t in ts)/len(ts),k)
        def take(ts):
            addition={t['id']:t for t in ts if t['id'] not in chosen}
            if addition and len(chosen)+len(addition)<=cap:
                prospective=chosen|addition
                missing={'B','P'}-{t['task'] for t in prospective.values()}
                # Reserve room for an intact unit of the other domain BEFORE
                # accepting a practice group; never repair by splitting it.
                for domain in missing:
                    costs=[len({t['id'] for t in unit}-prospective.keys())
                           for unit in plan['regular'].values()
                           if any(t['task']==domain for t in unit)]
                    if not costs or len(prospective)+min(costs)>cap:return False
                chosen.update(addition);return True
            return False
        role=('bridge','history','reduced','result')[s%4]
        for _,ts in sorted(plan['practice'][role].items(),key=rank):
            if take(ts):break
        for domain in ('B','P'):
            if any(t['task']==domain for t in chosen.values()):continue
            for _,ts in sorted(plan['regular'].items(),key=rank):
                if any(t['task']==domain for t in ts) and take(ts):break
        for _,ts in sorted(plan['regular'].items(),key=rank):take(ts)
        if {t['task'] for t in chosen.values()}!={'B','P'}:
            raise ValueError(f'No intact B/P pair fits original batch budget at step {s}')
        counts.update(chosen.keys());plan['batches'].append(list(chosen.values()))
    return plan['batches'][step]


def reset_order(rows, rng):
    """50% <=6 proposal slots, 25% 7–9, 25% >=10; intact resets."""
    if not any(t.get('sampling_version') == VERSION for t in rows):
        order = list(range(len(rows)))
        rng.shuffle(order)
        return order
    if not all(t.get('sampling_version') == VERSION for t in rows):
        raise ValueError('Partial self-play curriculum metadata')
    buckets = defaultdict(list)
    for i, t in enumerate(rows):
        slots = len(t['raw']['game']['round_robin'])
        buckets['short' if slots <= 6 else 'medium' if slots <= 9 else 'long'].append(i)
    if set(buckets) != {'short', 'medium', 'long'}:
        raise ValueError('Missing self-play horizon tier')
    for values in buckets.values():
        rng.shuffle(values)
    cursors = defaultdict(int)
    order = []
    # Every reset appears before this finite schedule repeats. Randomize phase
    # so even a small batch does not always begin with a short game.
    cycle = ['short', 'short', 'medium', 'long']
    offset = rng.randrange(4)
    cycle = cycle[offset:] + cycle[:offset]
    for _ in range(max(len(v) for v in buckets.values())):
        for tier in cycle:
            values = buckets[tier]
            order.append(values[cursors[tier] % len(values)])
            cursors[tier] += 1
    return order
