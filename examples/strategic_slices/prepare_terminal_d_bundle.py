"""Create a local transfer archive; no network, model launch or submission."""
import argparse
import io
import json
from pathlib import Path
import tarfile

from training.strategic_slices.common import file_hash, write_json
from training.strategic_slices.freeze import source_identity
from training.strategic_slices.terminal_d import ROOT, load_config, load_dataset


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path,
                        default=ROOT/'examples/strategic_slices/strategic-slices-terminal-D.tar.gz')
    args = parser.parse_args()
    cfg = load_config()
    data = ROOT/cfg['data']
    load_dataset(data)
    files = set(source_identity()) | {'training/__init__.py'}
    files.update(str(p.relative_to(ROOT)) for p in data.rglob('*') if p.is_file())
    files.update(str(p.relative_to(ROOT)) for p in (ROOT/'examples/strategic_slices').glob('*')
                 if p.is_file() and p.suffix in ('.py','.sh','.json','.md')
                 and not p.name.endswith('.tar.gz.json'))
    files.update(str(p.relative_to(ROOT)) for p in (ROOT/'examples/strategic_slices/fixtures').rglob('*') if p.is_file())
    files.update(cfg['historical_sources'])
    manifest = dict(files={name:file_hash(ROOT/name) for name in sorted(files)},
                    dataset_sha256=file_hash(data/'manifest.json'), model_weights_included=False,
                    submitted=False, entry='bash examples/strategic_slices/run_terminal_d.sh --check')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(args.output, 'x:gz') as archive:
        for name in sorted(files):
            archive.add(ROOT/name, arcname=name, recursive=False)
        payload = (json.dumps(manifest, indent=2)+'\n').encode()
        entry = tarfile.TarInfo('TERMINAL_D_BUNDLE.json'); entry.size=len(payload)
        archive.addfile(entry, io.BytesIO(payload))
    write_json(args.output.with_suffix(args.output.suffix+'.json'),
               dict(archive=args.output.name, sha256=file_hash(args.output), files=len(files), **{k:v for k,v in manifest.items() if k!='files'}))
    print(json.dumps(dict(archive=str(args.output), files=len(files), sha256=file_hash(args.output))))


if __name__ == '__main__':
    main()
