"""Build/verify a hash-bound code and frozen-data upload, excluding model/run files."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[2]
MANIFEST='bp_two_a100_bundle_manifest.json'

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def verify(root):
    root=Path(root)
    manifest=json.loads((root/MANIFEST).read_text())
    for name,expected in manifest['files'].items():
        if digest(root/name)!=expected:
            raise RuntimeError(f'Bundle mismatch: {name}')
    print(f"Verified {len(manifest['files'])} uploaded files")

def build(out):
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=False)
    files=set()
    for name in ('roll','training/b_sft','mcore_adapter','third_party/negotiation_benchmark/src'):
        files.update(p for p in (ROOT/name).rglob('*') if p.is_file() and p.suffix in ('.py','.cu','.cpp','.h','.json') and '__pycache__' not in p.parts and 'debug' not in p.parts)
    files.update((ROOT/'examples/config').glob('*.yaml'))
    files.add(ROOT/'mcore_adapter/requirements.txt')
    files.update(ROOT/'examples/social_bp'/name for name in ('grpo_two_a100_deepspeed.yaml','run_two_a100_train.sh'))
    files.update(ROOT/'examples/social_bp'/name for name in ('grpo.yaml','grpo_two_a100.yaml','grpo_two_a100_preflight.yaml','run_two_a100_preflight.sh','development_families.json','TWO_A100_PREFLIGHT.md'))
    files.update((ROOT/'examples/social_bp/data_two_a100_v1').glob('*'))
    # Some training validators import audit helper Python modules.
    files.update((ROOT/'training/b_sft/debug').glob('*.py'))
    manifest={}
    for src in sorted(files):
        rel=src.relative_to(ROOT);target=out/rel;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(src,target);manifest[str(rel)]=digest(target)
    (out/MANIFEST).write_text(json.dumps(dict(files=manifest),indent=2)+'\n')
    verify(out)
    print(out)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--output');group.add_argument('--verify')
    args=parser.parse_args()
    verify(args.verify) if args.verify else build(args.output)
