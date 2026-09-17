"""Copy a self-contained, hash-checked CPU/request runtime for rsync deployment."""
import argparse
import json
from pathlib import Path
import shutil

from prepare import HERE, ROOT, sha
from evaluate import load


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', type=Path, default=HERE / 'remote_bundle')
    a = p.parse_args(); manifest, _, _ = load()
    a.output.mkdir(parents=True, exist_ok=False)
    paths = {ROOT / name for name in manifest['dependencies']}
    paths.update(f for f in HERE.iterdir() if f.is_file() and f.suffix in ('.py', '.sh', '.json', '.jsonl', '.md'))
    for path in tuple(paths):
        for parent in path.relative_to(ROOT).parents:
            init = ROOT / parent / '__init__.py'
            if init.is_file(): paths.add(init)
    records = {}
    for path in sorted(paths):
        relative = path.relative_to(ROOT); destination = a.output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination); records[str(relative)] = sha(destination)
    (a.output / 'bundle_manifest.json').write_text(json.dumps(dict(
        diagnostic_manifest_sha256=sha(HERE / 'manifest.json'), files=records,
        scope='Isolated evaluation runtime; no model weights, optimizer, or remote checkout updates.'), indent=2) + '\n')
    print(json.dumps(dict(output=str(a.output), files=len(records),
                         bytes=sum((a.output / name).stat().st_size for name in records)), indent=2))


if __name__ == '__main__':
    main()
