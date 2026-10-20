"""Build a standalone CPU solver bundle from actual transitive project imports."""
import argparse
from hashlib import sha256
import importlib
import json
from pathlib import Path
import shutil
import sys
import tarfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'third_party/negotiation_benchmark/src'))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    bundle=args.output/'game_oracle_remote_v1';bundle.mkdir()
    # Include the lazy runtime dependency and the exact six CPU semantic tests.
    for name in ['new.strategic_game_v1_20261021.remote_solver',
                 'new.strategic_game_v1_20261021.test_rules',
                 'new.game_design_feasibility_20261021.test_design',
                 'training.strategic_slices.bounded','training.strategic_slices.equilibrium',
                 'training.strategic_slices.batched_response','training.strategic_slices.common']:
        importlib.import_module(name)
    modules=set()
    for module in list(sys.modules.values()):
        name=getattr(module,'__file__',None)
        if not name:continue
        path=Path(name).resolve()
        if path.is_relative_to(ROOT) and path.suffix=='.py':modules.add(path.relative_to(ROOT))
    modules.add(Path(__file__).relative_to(ROOT))
    extras=[Path('examples/strategic_slices/REMOTE_SOLVER_20261021.md'),
        Path('examples/strategic_slices/solve_parents_100_cpu.sbatch')]
    pool=Path('new/strategic_game_v1_20261021/parents_100_v1')
    extras += [pool/name for name in ('parents.jsonl','manifest.json','pipeline_snapshot.json')]
    for rel in sorted(modules|set(extras)):
        dst=bundle/rel;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/rel,dst)
    (bundle/'requirements-oracle.txt').write_text('numpy==1.26.4\nscipy==1.12.0\n')
    from new.strategic_game_v1_20261021.remote_solver import VERSION,PROFILES
    protocol=dict(version=VERSION,profiles=PROFILES,
        workers='0=auto, min(4, allocated CPUs); CLI override recorded',
        construct_seconds=120,max_nodes=100000,epsilon=1e-8,tie_tolerance=1e-9,
        independent_native_terminal_audit=True,policy_selection='first certified declared start',
        source='Frozen current repository files; uncommitted files included explicitly',
        model_GPU_prompt_Q_S_D_training='Not used or changed',
        data_sha256=sha256((ROOT/pool/'parents.jsonl').read_bytes()).hexdigest())
    (bundle/'PROTOCOL.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2)+'\n')
    files={str(p.relative_to(bundle)):sha256(p.read_bytes()).hexdigest()
           for p in sorted(bundle.rglob('*')) if p.is_file()}
    manifest=dict(version='strategic-parent-remote-bundle-v1',runner_version=VERSION,
        files=files,python='3.10-3.12; recommended 3.12',no_gpu_dependencies=True)
    (bundle/'BUNDLE_MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    archive=args.output/'game_oracle_remote_v1.tar.gz'
    with tarfile.open(archive,'w:gz') as tar:tar.add(bundle,arcname=bundle.name)
    archive_hash=sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(archive.suffix+'.sha256').write_text(archive_hash+'  '+archive.name+'\n')
    print(json.dumps(dict(archive=str(archive),sha256=archive_hash,files=len(files),bytes=archive.stat().st_size),ensure_ascii=False))


if __name__=='__main__':main()
