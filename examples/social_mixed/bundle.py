"""Package only required source and prepared data for user-operated rsync."""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile

ROOT=Path(__file__).resolve().parents[2]


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--output',type=Path,default=Path('/private/tmp/marshal-social-mixed-v1.tar.gz'))
    args=cli.parse_args()
    roots=('roll','mcore_adapter/src','training/b_sft','training/social_mixed',
           'third_party/negotiation_benchmark/src','examples/social_mixed')
    files={}
    for name in roots:
        for p in (ROOT/name).rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts and p.suffix in ('.py','.yaml','.yml','.json','.jsonl','.sh','.jinja','.j2','.md'):
                if p.name=='bundle_manifest.json':continue
                if 'debug' in p.parts and p.suffix!='.py':continue
                files[str(p.relative_to(ROOT))]=hashlib.sha256(p.read_bytes()).hexdigest()
    if (ROOT/'training/__init__.py').exists():
        files['training/__init__.py']=hashlib.sha256((ROOT/'training/__init__.py').read_bytes()).hexdigest()
    manifest=ROOT/'examples/social_mixed/bundle_manifest.json'
    manifest.write_text(json.dumps(dict(version='social-mixed-v1',files=files),indent=2)+'\n')
    with tarfile.open(args.output,'w:gz') as tar:
        for name in sorted(files):tar.add(ROOT/name,arcname=name,recursive=False)
        tar.add(manifest,arcname=str(manifest.relative_to(ROOT)),recursive=False)
    checksum=hashlib.sha256(args.output.read_bytes()).hexdigest()
    args.output.with_suffix('.sha256').write_text(f'{checksum}  {args.output.name}\n')
    print(json.dumps(dict(archive=str(args.output),sha256=checksum,bytes=args.output.stat().st_size,files=len(files)),indent=2))


if __name__=='__main__':main()
