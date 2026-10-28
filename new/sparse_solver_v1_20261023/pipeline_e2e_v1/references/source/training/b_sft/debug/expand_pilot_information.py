"""Explore actual known-payoff neighbors of verified information contrasts."""
import argparse
from copy import deepcopy
import json
from pathlib import Path

from training.b_sft.build_bp_information import information_tasks
from training.b_sft.shared_teacher import SearchLimit


def main():
    p = argparse.ArgumentParser(); p.add_argument('--out', required=True); p.add_argument('--limit', type=int, default=240)
    a = p.parse_args(); root = Path(a.out); root.mkdir(parents=True, exist_ok=True)
    seeds = []
    for name in ('bp_pilot_information', 'bp_pilot_information_v2'):
        for line in Path(f'new/local_data/social_runs/{name}/search.jsonl').read_text().splitlines():
            r = json.loads(line)
            if r.get('positive'): seeds.append(r)
    proposals = []; seen = set()
    for seed in seeds:
        raw = seed['raw']
        for player in (0, 1):
            rows = raw['type_catalogues'][str(player)]
            for g in range(len(raw['game']['goals'])):
                if len({r[g] for r in rows}) != 1: continue
                for v in (-1,0,1):
                    if v == rows[0][g]: continue
                    changed = deepcopy(raw)
                    for row in changed['type_catalogues'][str(player)]: row[g] = v
                    if player == 0: changed['own_preferences'][g] = v
                    key = json.dumps([changed['game'], changed['type_catalogues']], sort_keys=True)
                    if key in seen: continue
                    seen.add(key)
                    changed['id'] += f'-p{player}g{g}v{v}'
                    proposals.append((seed['stage'], changed))
    positives = [0,0,0]
    with (root/'tasks.jsonl').open('w') as tf, (root/'search.jsonl').open('w') as sf:
        for i, (stage, raw) in enumerate(proposals[:a.limit]):
            r = dict(index=i, stage=stage, raw=raw)
            try:
                tasks, audit = information_tasks(raw, stage); r.update(status='solved', **audit)
                positives[stage] += audit['positive']
                for t in tasks: tf.write(json.dumps(t)+'\n')
            except (SearchLimit, ValueError) as exc: r.update(status='no_label', reason=str(exc))
            sf.write(json.dumps(r)+'\n'); sf.flush(); tf.flush()
            if i % 20 == 0: print(json.dumps(dict(index=i, positives=positives)), flush=True)
    print(json.dumps(dict(positives=positives, proposals=len(proposals))))


if __name__ == '__main__': main()
