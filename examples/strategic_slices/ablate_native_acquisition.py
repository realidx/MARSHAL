"""Small native controls around the certified three-player acquisition witness."""
import argparse
from copy import deepcopy
import json
from pathlib import Path

from examples.strategic_slices.search_native_acquisition import evaluate_parent
from training.b_sft.preference_contract import profile
from training.strategic_slices.common import file_hash, write_json


def controls(raw):
    for name in ('want_heavy', 'neutral_heavy', 'avoid_heavy'):
        variant = deepcopy(raw)
        variant['background_prior'] = profile(name)
        yield 'prior_' + name, variant
    variant = deepcopy(raw)
    variant['game']['goals'][3]['required_actions'].pop(1)
    yield 'one_own_action_in_bonus_goal', variant
    variant = deepcopy(raw)
    variant['game']['goals'][3]['binary'] = False
    yield 'linear_bonus_goal', variant
    variant = deepcopy(raw)
    variant['type_catalogues']['1'][0][2] = 1
    yield 'public_want_on_avoid_only_goal', variant


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if (args.output / 'config.json').exists():
        raise ValueError('Use a new output directory')
    source = Path('examples/strategic_slices/fixtures/native_acquisition_three_player.json')
    raw = json.loads(source.read_text())['raw']
    write_json(args.output / 'config.json', dict(source_sha256=file_hash(source),
        script_sha256=file_hash(Path(__file__)), evaluator_sha256=file_hash(Path('examples/strategic_slices/search_native_acquisition.py')),
        scope='Each changed parent is independently solved from its native initial state. Results concern the selected certified profiles; equilibrium-selection effects are included, not held fixed.'))
    results = []
    for name, variant in controls(raw):
        result = evaluate_parent(variant, name, args.output, 60, 160000)
        results.append(result)
        write_json(args.output / 'summary.json', dict(results=results))
        print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
