"""Native information-action contrasts, with an explicit counterfactual audit."""
import argparse
from copy import copy, deepcopy
from itertools import product
import json
from pathlib import Path
import random

import numpy as np

from training.b_sft.build_bp_pilot import make_task, topology, final_setup
from training.b_sft.debug.search_private_voi_pilot import candidate
from training.b_sft.prepare_named_bridge_probe import acquisition_fixture
from training.b_sft.prepare_no_catalogue_probe import expand_support
from training.b_sft.social_private_teacher import PrivateEpisode, audit_native
from training.b_sft.shared_teacher import SearchLimit
from training.b_sft.social_bp_curriculum import acceptable


def candidates(count):
    base = candidate(650)
    social, _ = acquisition_fixture()
    # This round-boundary order is permitted by the native game: each round
    # still gives every player one proposal. It is never silently substituted
    # for a fixed-order game in scoring or outcome self-play.
    for seed in range(count):
        rng = random.Random(10000+seed)
        stage = seed % 3
        raw = json.loads(json.dumps(social if stage == 1 else base))
        extras = rng.choice([0, 1, 2])
        if extras:
            options = [[(0,0),(1,0)], [(0,0),(1,1)], [(0,1),(1,0)], [(0,1),(1,1)],
                       [(0,0),(0,1),(1,0)], [(0,0),(0,1),(1,1)],
                       [(0,0),(1,0),(1,1)], [(0,1),(1,0),(1,1)]]
            for _ in range(extras):
                req = rng.choice(options)
                raw['game']['goals'].append(dict(goal_id=len(raw['game']['goals']), binary=True,
                    required_actions=[dict(player_id=p, action_id=a) for p, a in req]))
                own, other = rng.choice([(1,0),(0,1),(1,1),(-1,1),(1,-1),(0,-1)])
                raw['own_preferences'].append(own)
                for row in raw['type_catalogues']['0']: row.append(own)
                for row in raw['type_catalogues']['1']: row.append(other)
        elif seed > 2 and stage < 2:
            g = rng.randrange(1, len(raw['game']['goals']))
            raw['own_preferences'][g] = rng.choice([-1,0,1])
            raw['type_catalogues']['0'][0][g] = raw['own_preferences'][g]
            other = rng.choice([0,1]) if g < 2 else 1
            for row in raw['type_catalogues']['1']: row[g] = other
        if stage == 2:
            rows = []
            for old in raw['type_catalogues']['1']:
                for v in (1,0,-1):
                    row = old.copy(); row[1] = v; rows.append(row)
            raw['type_catalogues']['1'] = rows
        raw['id'] = f'pilot-information-{seed}'
        order = list(range(len(raw['game']['goals']))); rng.shuffle(order)
        raw['game']['goals'] = [dict(raw['game']['goals'][old], goal_id=new) for new, old in enumerate(order)]
        raw['own_preferences'] = [raw['own_preferences'][old] for old in order]
        raw['type_catalogues'] = {p: [[row[old] for old in order] for row in rows] for p, rows in raw['type_catalogues'].items()}
        yield seed, raw, stage


def information_tasks(raw, stage):
    raw, public, _ = expand_support(raw); family = topology(raw); setup = raw.get('pilot_setup', [dict(action='PASS')])
    e = PrivateEpisode(raw, setup, seconds=4, max_nodes=40000)
    choices = e.choices(raw['own_preferences']); accepted = acceptable(choices['values'], 0)
    query_ids = [i for i, a in enumerate(choices['actions']) if a.get('action') == 'INVESTIGATE']
    ordinary_ids = [i for i in range(len(choices['actions'])) if i not in query_ids]
    best_query = max(query_ids, key=lambda i: choices['values'][i][0])
    own_gap = choices['values'][best_query][0]-max(choices['values'][i][0] for i in ordinary_ids)
    positive = all(i in query_ids for i in accepted)
    negative = all(i in ordinary_ids for i in accepted)
    tasks = []
    if positive or negative:
        t = make_task(e, public, setup, [], 'P', stage, family, pool='information', source=raw['id'])
        if t:
            t['information_positive'] = positive; t['teacher']['own_query_margin'] = own_gap
            t['teacher']['selection_contract'] = e.tree.certificate['selection_contract']
            tasks.append(t)
    if positive:
        # Full tree computation already includes the exact proposal order.
        # Check use of the answer at the next learner checkpoint separately.
        q = choices['actions'][accepted[0]]; branch = copy(e); branch.observe(q)
        entry = branch.tree.entries[branch.index]
        if entry.actor == 0:
            weights = branch.weights/branch.weights.sum()
            av = np.array([branch.tree.values[c] for c in entry.children])
            blind = np.einsum('awp,w->ap', av, weights)
            informed = np.average(branch.tree.values[branch.index], axis=0, weights=weights)
            t['teacher']['answer_use_ablation'] = dict(public_history=[q],
                informed_value=informed.tolist(), best_blind_own=float(blind[:,0].max()),
                scope='Hold this public history and partner continuation fixed; remove only answer-conditioned learner choice')
        rr, ss = final_setup(raw, 0)
        deadline = PrivateEpisode(rr, ss)
        contrast = make_task(deadline, public, ss, [], 'P', stage, family, pool='information', source=raw['id'])
        if contrast and all(a.get('action') != 'INVESTIGATE' for a in contrast['teacher']['acceptable_actions']):
            contrast['information_positive'] = False; contrast['information_negative_kind'] = 'last_opportunity'
            tasks.append(contrast)
    if negative and tasks:
        tasks[0]['information_negative_kind'] = 'future_opportunity_remains'
    return tasks, dict(nodes=len(e.tree.entries), own_gap=own_gap, positive=positive, negative=negative,
                      native=audit_native(e.tree))


def main():
    p = argparse.ArgumentParser(); p.add_argument('--out', required=True); p.add_argument('--count', type=int, default=240)
    a = p.parse_args(); out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    seen = set(); totals = [0,0,0]
    with (out/'tasks.jsonl').open('w') as tf, (out/'search.jsonl').open('w') as sf:
        for seed, raw, stage in candidates(a.count):
            signature = json.dumps([raw['game'], raw['type_catalogues']], sort_keys=True)
            if signature in seen: continue
            seen.add(signature)
            record = dict(seed=seed, stage=stage, raw=raw)
            try:
                tasks, audit = information_tasks(raw, stage); record.update(status='solved', **audit)
                for t in tasks: tf.write(json.dumps(t)+'\n')
                if audit['positive']: totals[stage] += 1
            except (ValueError, SearchLimit) as exc: record.update(status='no_label', reason=str(exc))
            sf.write(json.dumps(record)+'\n'); sf.flush(); tf.flush()
            if seed % 10 == 0: print(json.dumps(dict(seed=seed, positives=totals)), flush=True)
    print(json.dumps(dict(positive_counts=totals)))


if __name__ == '__main__': main()
