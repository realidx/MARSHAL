"""Run mock CPU collection and validation; never claim these are model results."""
import argparse
from pathlib import Path
from .common import Dataset, write_json
from .runtime import Collector
from .evaluate import Evaluator
from .test_pipeline import mock_generate


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--data', required=True, type=Path)
    cli.add_argument('--output', required=True, type=Path)
    args = cli.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    dataset = Dataset(args.data)
    results = dict(mock_only=True, actual_model_or_optimizer=False)
    for arm in ('slices', 'selfplay'):
        collector = Collector(dataset, mock_generate, arm)
        updates = []
        for step in range(2):
            rows, units, games, metrics = collector.collect(step, arm, 64)
            updates.append(metrics)
        restored = Collector(dataset, mock_generate, arm)
        restored.restore(collector.state)
        if collector.collect(2, arm, 64) != restored.collect(2, arm, 64):
            raise AssertionError('Exposure recovery mismatch')
        results[arm] = dict(updates=updates, exposure=collector.state['exposure'])
    evaluation = Evaluator(dataset, mock_generate).run()
    write_json(args.output / 'validation.json', evaluation)
    write_json(args.output / 'COMPLETE.json', results)
    print(results)


if __name__ == '__main__':
    main()
