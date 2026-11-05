"""Bounded native teaching-game search; records failures and real VOI margins."""
import argparse
from itertools import product
import json
from pathlib import Path
import random
import time

from training.b_sft.prepare_no_catalogue_probe import expand_support
from training.b_sft.social_private_teacher import PrivateEpisode
from training.b_sft.shared_teacher import SearchLimit
from training.b_sft.social_bp_curriculum import acceptable


def candidate(seed):
    rng = random.Random(seed)
    pairs = [(0, 1), (0, 0), (1, 0), (1, 1)]
    n_goals = rng.choice([3, 4, 5])
    requirements = pairs[:3] if n_goals == 3 else pairs + ([rng.choice(pairs)] if n_goals == 5 else [])
    own = [rng.choice([-1, 0, 1]) for _ in requirements]
    if 1 not in own: own[-1] = 1
    partner = [rng.choice([-1, 0, 1]) for _ in requirements]; partner[-1] = 1
    hidden = [0] if rng.random() < .65 else [0, 1]
    rows = []
    for values in product((1, 0, -1), repeat=len(hidden)):
        row = partner.copy()
        for q, v in zip(hidden, values): row[q] = v
        rows.append(row)
    own_rows = [own]
    if 300 <= seed < 600:
        own[0] = 1
        own_rows = [own[:-1]+[v] for v in (1, 0, -1)]
    raw = dict(id=f'pilot-voi-{seed}', ego=0, own_preferences=own, history=[],
        type_catalogues={'0': own_rows, '1': rows},
        game=dict(n_players=2, n_actions_per_player=[2, 2], max_changes=1, menu_enabled=False,
                  round_robin=[1, 0, 1, 0], goals=[dict(goal_id=g, binary=True,
                    required_actions=[dict(player_id=0, action_id=a), dict(player_id=1, action_id=b)])
                    for g, (a, b) in enumerate(requirements)]))
    if seed >= 600:
        raw['game']['round_robin'] = [1, 0, 0, 1]
    return raw


def search(out, start, count):
    path = Path(out); path.parent.mkdir(parents=True, exist_ok=True)
    found = 0
    with path.open('w') as stream:
        for seed in range(start, start+count):
            row = dict(seed=seed); started = time.monotonic()
            try:
                raw, public, _ = expand_support(candidate(seed))
                e = PrivateEpisode(raw, [dict(action='PASS')], seconds=1.5, max_nodes=30000)
                choices = e.choices(raw['own_preferences'])
                ordinary = [v[0] for a, v in zip(choices['actions'], choices['values']) if a.get('action') != 'INVESTIGATE']
                queries = [(i, a, v) for i, (a, v) in enumerate(zip(choices['actions'], choices['values'])) if a.get('action') == 'INVESTIGATE']
                i, action, value = max(queries, key=lambda x: x[2][0])
                gap = value[0]-max(ordinary)
                row.update(status='solved', gap=gap, nodes=len(e.tree.entries))
                if gap > .10000001 and i in acceptable(choices['values'], 0, actions=choices['actions']):
                    row.update(raw=raw, query=action, root=choices, certificate=e.tree.certificate)
                    found += 1
                    print(json.dumps(dict(found=seed, gap=gap)), flush=True)
            except (SearchLimit, ValueError) as exc:
                row.update(status='no_label', reason=str(exc))
            row['seconds'] = time.monotonic()-started
            stream.write(json.dumps(row)+'\n'); stream.flush()
            if seed % 25 == 0: print(json.dumps(dict(seed=seed, found=found)), flush=True)
            if found >= 8: break


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--out', required=True); p.add_argument('--start', type=int, default=0); p.add_argument('--count', type=int, default=300)
    a = p.parse_args(); search(a.out, a.start, a.count)
