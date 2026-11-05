"""Recorded import bootstrap for the frozen paired report and witness methods."""
import argparse
import importlib
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
VERSION='A2H2-audit-runtime-v3'
REG=ROOT/'examples/strategic_slices/versions/A2H2_audit_runtime_v3_20261025/SNAPSHOT.json'


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('method',choices=['paired','LP'])
    args,rest=parser.parse_known_args()
    launch_argv=list(sys.argv)
    incoming_pythonpath=os.environ.get('PYTHONPATH','NOT_RECORDED')
    for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS'):
        os.environ[name]='1'
    dependency=ROOT/'third_party/negotiation_benchmark/src'
    sys.path.insert(0,str(dependency));sys.path.insert(0,str(ROOT))
    from new.three_player_complexity_v1_20261023 import common as c
    original_snapshot=c.snapshot
    def snapshot(output,config,inputs=None):
        config=dict(config,launch=dict(argv=launch_argv,method=args.method,
            incoming_PYTHONPATH=incoming_pythonpath,resolved_sys_path=list(sys.path),
            import_bootstrap='Explicit repository root and negotiation_benchmark/src before domain imports',
            environment_overrides={key:os.environ[key] for key in
                ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS')}))
        return original_snapshot(output,config,inputs)
    c.snapshot=snapshot
    name='new.report_A2H2_paired_20261024' if args.method=='paired' else 'new.review_A2H2_witnesses_20261025'
    module=importlib.import_module(name)
    module.VERSION,module.REG=VERSION,REG
    # Preserve the actual bootstrap argv in resolved_config.launch. The called
    # frozen parser receives only its own method arguments.
    sys.argv=[name]+rest
    module.main()


if __name__=='__main__':main()
