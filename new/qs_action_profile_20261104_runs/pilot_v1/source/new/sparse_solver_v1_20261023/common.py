"""Run identity for isolated CPU solver research; never a training run."""
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import importlib.metadata

import numpy as np
import scipy

from training.strategic_slices.freeze import source_identity

ROOT = Path(__file__).resolve().parents[2]
POOL = ROOT / 'new/strategic_game_v1_20261021/parents_100_v1/parents.jsonl'
POOL_SHA = '30fb0f7d012f33f5d175650258698e9ba46cd88cafc64da39f848a69c4bfd3ad'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def snapshot(output, config):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    assert sha(POOL) == POOL_SHA
    sources = source_identity()
    for folder in ('new/sparse_solver_v1_20261023', 'new/strategic_game_v1_20261021',
                   'new/game_design_feasibility_20261021'):
        for path in (ROOT / folder).glob('*.py'):
            sources[str(path.relative_to(ROOT))] = sha(path)
    for rel in sources:
        dest = output / 'source' / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, dest)
    optional={}
    for package in ('pygambit','nashpy'):
        try:optional[package]=importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:optional[package]='NOT_ON_ACTIVE_PYTHON_PATH'
    write(output / 'pipeline_snapshot.json', dict(
        version='sparse-sequence-solver-research-v1', date='2026-10-23',
        actual_argv=sys.argv, resolved_config=config, source_hashes=sources,
        data=dict(path=str(POOL.relative_to(ROOT)), sha256=POOL_SHA),
        environment=dict(python=sys.version, executable=sys.executable,
            numpy=np.__version__, scipy=scipy.__version__, platform=platform.platform(),
            optional_packages=optional,
            threads={k:os.environ.get(k, 'NOT_RECORDED') for k in
                     ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS',
                      'VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS','PYTHONPATH')}),
        model='NOT_USED', prompt='NOT_USED', D='NOT_MEASURED', S='NOT_MEASURED',
        training_reward_advantage='NOT_APPLICABLE', production_changed=False,
        production_active='terminal-node-regret-grpo-readable-v8'))


def parents():
    assert sha(POOL) == POOL_SHA
    return list(map(json.loads, POOL.read_text().splitlines()))
