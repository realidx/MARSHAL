"""Summarize native Lite outputs without equating CLI exit with task success."""
import argparse
import json
from pathlib import Path

import yaml


def summarize(root):
    root = Path(root)
    manifest = json.loads((root / 'manifest.json').read_text())
    rows = []
    for job in manifest['jobs']:
        name = job['id']
        cfg = yaml.safe_load((root / (name + '.yml')).read_text())
        expected = [a['id'] for a in cfg['agents']]
        orders = cfg['task']['shapes_order']
        path = root / name / 'run_summary.json'
        summary = json.loads(path.read_text()) if path.exists() else {}
        agents = summary.get('per_agent', {})
        exit_path = root / (name + '.exit_code')
        exit_code = int(exit_path.read_text()) if exit_path.exists() else None
        observed = all(a in agents for a in expected)
        fulfilled = sum(min(orders, agents.get(a, {}).get('order_progress', 0)) for a in expected)
        rows.append(dict(
            id=name, process_exit_code=exit_code,
            result_available=observed,
            infrastructure_valid=exit_code == 0 and observed,
            native_complete=summary.get('complete'),
            fulfilled_order_items=fulfilled if observed else None,
            total_order_items=orders * len(expected),
            all_orders_fulfilled=fulfilled == orders * len(expected) if observed else None,
            mean_final_balance=sum(agents[a]['final_balance'] for a in expected) / len(expected) if observed else None,
            completed_trades=summary.get('task_summary', {}).get('completed_trades'),
            per_agent={a: {k: v for k, v in data.items() if k != 'probe_responses'} for a, data in agents.items()},
        ))
    # Partial/failed runs remain explicit; do not silently average only survivors.
    valid = all(r['infrastructure_valid'] for r in rows) and bool(rows)
    result = dict(version='native-lite-summary-v1', games=rows, all_runs_valid=valid,
                  note='Infrastructure validity here checks exit and summary presence only; inspect service/probe errors separately.')
    if valid:
        result['aggregate'] = dict(
            fulfilled_order_items=sum(r['fulfilled_order_items'] for r in rows),
            total_order_items=sum(r['total_order_items'] for r in rows),
            all_orders_fulfilled_games=sum(r['all_orders_fulfilled'] for r in rows),
            games=len(rows),
            mean_final_balance=sum(r['mean_final_balance'] for r in rows) / len(rows),
        )
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path, help='Directory containing manifest.json and native game folders')
    args = parser.parse_args()
    print(json.dumps(summarize(args.root), indent=2))
