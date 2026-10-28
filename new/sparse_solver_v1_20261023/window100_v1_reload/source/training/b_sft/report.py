"""Readable learning curve and selected-model path; no GPU dependencies."""

import argparse
import json
from pathlib import Path


def render(run_dir):
    root = Path(run_dir)
    curve = root / 'semantic_curve.jsonl'
    if not curve.exists():
        raise ValueError('No semantic curve found; run with --semantic-eval')
    # A crash/resume may repeat a step; use the most recent completed report.
    steps = {}
    for line in curve.read_text().splitlines():
        row = json.loads(line)
        steps[row['step']] = row
    def percent(value):
        return '—' if value is None else f'{100 * value:.1f}%'
    lines = ['| Step | Epoch | Eval loss | Source macro exact | Format | Maintain pair | Update pair | Train probe exact |',
             '|---:|---:|---:|---:|---:|---:|---:|---:|']
    for step, row in sorted(steps.items()):
        val = row['metrics'][row.get('evaluation_split', 'validation')]
        probe = row['metrics'].get('train_probe', {}).get('overall', {}).get('exact_rate_all')
        loss = row['loss_metrics'].get('eval_loss')
        lines.append('| ' + ' | '.join([str(step), f"{row['epoch'] or 0:.2f}",
                     '—' if loss is None else f'{loss:.4f}', percent(val['source_macro_exact']),
                     percent(val['overall']['format_success_rate']),
                     percent(val['pairs']['maintain']['both_exact_rate_all']),
                     percent(val['pairs']['update']['both_exact_rate_all']), percent(probe)]) + ' |')
    selection = root / 'selection.json'
    if selection.exists():
        value = json.loads(selection.read_text())
        lines += ['', f"Selected model: {value['selected_model']}",
                  'Original model retained: no trained checkpoint strictly improved validation.' if value['selected_original']
                  else 'Selected checkpoint must be CPU-exported before ordinary HF loading.']
    split = list(steps.values())[-1].get('evaluation_split', 'validation') if steps else 'validation'
    lines += ['', 'Pair denominators include invalid/missing answers. Train probe is diagnostic only.',
              f'Inspect semantic/step-NNNNNN/{split}/questions.csv and pairs.csv for individual errors.']
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_dir')
    args = parser.parse_args()
    result = render(args.run_dir)
    (Path(args.run_dir) / 'semantic_report.md').write_text(result)
    print(result)


if __name__ == '__main__':
    main()
