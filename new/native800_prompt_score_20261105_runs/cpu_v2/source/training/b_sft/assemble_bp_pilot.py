"""Assemble certified candidate pools without using learner performance."""
import argparse
import json
from pathlib import Path
from training.b_sft.build_bp_pilot import write_dataset


def main():
    p = argparse.ArgumentParser(); p.add_argument('--tasks', nargs='+', required=True)
    p.add_argument('--search-logs', nargs='*', default=[]); p.add_argument('--out', required=True)
    a = p.parse_args(); tasks = []; failures = []; provenance = []
    import hashlib
    for path in a.tasks+a.search_logs:
        src = Path(path); rows = [json.loads(s) for s in src.read_text().splitlines() if s.strip()]
        provenance.append(dict(path=str(src), sha256=hashlib.sha256(src.read_bytes()).hexdigest(), records=len(rows)))
        if path in a.tasks: tasks.extend(rows)
        else:
            failures.extend(dict(source_file=path, **r) for r in rows if r.get('status') == 'no_label' or 'reason' in r)
    result = write_dataset(tasks, a.out, failures)
    (Path(a.out)/'generation_provenance.json').write_text(json.dumps(dict(sources=provenance, rejected_candidates=len(failures),
        scope='Nonconvergence/budget/legality failures are logged and excluded, not classified as unsolvable games.'), indent=2)+'\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__': main()
