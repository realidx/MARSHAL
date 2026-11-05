"""Build a small model-independent acceptance pool, not a random-yield study.

Eight source-derived information-acquisition geometries vary goal scoring;
eight native three-player mixed-incentive triangles vary goal scoring. The
latter has two private worlds and no dummy player. Structural-family splitting
is still enforced by build; score changes are part of its declared topology.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path

from training.b_sft.preference_contract import profile
from .common import file_hash, write_json

SOURCE = Path(__file__).resolve().parents[2] / 'examples/strategic_slices/fixtures/information_acquisition.json'


def candidates():
    source = json.loads(SOURCE.read_text())
    rows = []
    for mask in range(8):
        raw = deepcopy(source['raw'])
        for g in range(3):
            raw['game']['goals'][g]['binary'] = bool(mask & (1 << g))
        raw['game']['round_robin'] = [1, 0] + raw['game']['round_robin']
        # Public exogenous PASS histories have likelihood independent of type.
        raw['slice_setup_histories'] = [[0, 0, 0]]
        rows.append(raw)
    for mask in range(8):
        goals = [dict(goal_id=g, binary=bool(mask & (1 << g)),
            required_actions=[dict(player_id=p, action_id=0) for p in pair])
            for g, pair in enumerate(((0, 1), (1, 2), (0, 2)))]
        rows.append(dict(ego=0, own_preferences=[1, 0, -1],
            type_catalogues={'0': [[1, 0, -1]], '1': [[1, 1, 0], [1, 1, -1]], '2': [[-1, 1, 1]]},
            background_prior=profile('balanced'),
            game=dict(n_players=3, n_actions_per_player=[1, 1, 1], goals=goals,
                      max_changes=1, menu_enabled=False, round_robin=[0, 1, 2]*3)))
    return rows


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--output', type=Path, required=True)
    args = cli.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as output:
        for row in candidates():
            output.write(json.dumps(row) + '\n')
    write_json(args.output.with_suffix('.meta.json'), dict(
        scope='Designed acceptance coverage; not random yield or a frozen 100/20/40 research corpus',
        parents=16, players={'2': 8, '3': 8}, source=str(SOURCE.relative_to(SOURCE.parents[3])),
        source_sha256=file_hash(SOURCE), pool_sha256=file_hash(args.output)))


if __name__ == '__main__':
    main()
