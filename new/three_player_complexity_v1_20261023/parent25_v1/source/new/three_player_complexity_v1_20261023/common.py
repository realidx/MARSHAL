"""Independent study identity; never mutates the old100 or production sources."""
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import sys

import numpy as np
import scipy

ROOT=Path(__file__).resolve().parents[2]
VERSION='three-player-complexity-study-v1'
REG=ROOT/'examples/strategic_slices/versions/three_player_complexity_v1_20261023/SNAPSHOT.json'
ORIGINAL=ROOT/'new/strategic_game_v1_20261021/parents_100_v1/parents.jsonl'
ORIGINAL_SHA='30fb0f7d012f33f5d175650258698e9ba46cd88cafc64da39f848a69c4bfd3ad'


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def stable(x):return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False)


def write(p,x):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    temp=p.with_suffix(p.suffix+'.tmp');temp.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
    temp.replace(p)


def parents():
    assert sha(ORIGINAL)==ORIGINAL_SHA
    return list(map(json.loads,ORIGINAL.read_text().splitlines()))


def snapshot(out,config,inputs=None):
    meta=json.loads(REG.read_text());assert meta['version']==VERSION
    for p,h in meta['source_hashes'].items():assert sha(ROOT/p)==h,f'Source changed: {p}'
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    for p in meta['source_hashes']:
        target=out/'source'/p;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/p,target)
    shutil.copyfile(REG,out/'registered_snapshot_at_start.json')
    write(out/'pipeline_snapshot.json',dict(version=VERSION,actual_argv=sys.argv,
        resolved_config=config,source_hashes=meta['source_hashes'],registration_sha256=sha(REG),
        original_pool=dict(path=str(ORIGINAL.relative_to(ROOT)),sha256=ORIGINAL_SHA),
        inputs=inputs or {},environment=dict(python=sys.version,executable=sys.executable,
            numpy=np.__version__,scipy=scipy.__version__,platform=platform.platform(),
            threads={k:os.environ.get(k,'NOT_RECORDED') for k in
                ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS')}),
        model='NOT_USED',prompt='NOT_CHANGED_NOT_USED',D='NOT_MEASURED',
        training_reward_advantage='NOT_CHANGED_NOT_USED',production_active='terminal-node-regret-grpo-readable-v8'))


def identity(p):return dict(path=str(Path(p).resolve().relative_to(ROOT)),sha256=sha(p))
