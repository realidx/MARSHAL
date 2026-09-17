"""Install the pinned public CalBench source snapshot without changing packages."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path,help='Use an already downloaded official ZIP')
    args=parser.parse_args()
    manifest=json.loads(Path(__file__).with_name('calbench_source.json').read_text())
    target=ROOT/'third_party/calbench'
    target.parent.mkdir(exist_ok=True)
    if target.exists():
        for name,digest in manifest['files'].items():
            path=target/name
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
                raise ValueError(f'Existing source differs: {name}; preserved without modification')
        print('Pinned source already installed');return
    with tempfile.TemporaryDirectory(prefix='calbench-setup-',dir=target.parent) as temp:
        temp=Path(temp);archive=args.archive
        if archive is None:
            archive=temp/'source.zip'
            subprocess.run(['curl','--fail','--location','--max-time','120','--output',str(archive),
                'https://anonymous.4open.science/api/repo/calbench2026-235F/zip'],check=True)
        stage=temp/'source';stage.mkdir()
        with zipfile.ZipFile(archive) as z:
            for name,digest in manifest['files'].items():
                relative=Path(name)
                if relative.is_absolute() or '..' in relative.parts:raise ValueError(name)
                content=z.read(name)
                if hashlib.sha256(content).hexdigest()!=digest:
                    raise ValueError(f'Upstream snapshot changed: {name}; not installed')
                dest=stage/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(content)
        stage.rename(target)
    print('Pinned CalBench source installed')


if __name__=='__main__':main()
