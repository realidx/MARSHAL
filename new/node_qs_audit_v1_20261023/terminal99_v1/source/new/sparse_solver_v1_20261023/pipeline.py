"""One-command CPU pipeline for the approved bounded reference contract."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from .common import ROOT,sha,snapshot,write


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--workers',type=int,default=2);args=parser.parse_args()
    if args.workers<1:parser.error('Positive CPU worker count required')
    registered=ROOT/'examples/strategic_slices/versions/terminal_solver_repair_v6_20261023/SNAPSHOT.json'
    if not registered.exists():raise ValueError('Register the research version before invoking the pipeline')
    version=json.loads(registered.read_text())
    assert all(sha(ROOT/p)==h for p,h in version['source_hashes'].items()),'Source differs from registered research snapshot'
    snapshot(args.output,dict(operation='bounded reference generation -> retries -> independent100 reload',
        registered_version=version['version'],registered_snapshot_sha256=sha(registered),
        workers=args.workers,game_pool='frozen100 unchanged',horizon='approved v2 next-own-proposal',
        stage1='window_run: 30s, uniform/first/last ordered/synchronous inertia',
        stage2='missing only: all player orders then joint; same bounded objective',
        stage3='all100 independent complete bounded-tree BR, privacy, support, response tie and native audits',
        Q='NOT_COMPUTED',S='NOT_COMPUTED',D='NOT_MEASURED',training_ready=False))
    def run(module,*arguments):
        subprocess.run([sys.executable,'-m',f'new.sparse_solver_v1_20261023.{module}',*map(str,arguments)],
                       cwd=ROOT,check=True)
    run('window_run','--output',args.output/'search','--workers',args.workers)
    results=json.loads((args.output/'search/results.json').read_text())
    missing=[r['index'] for r in results if r['status']!='certified_bounded']
    extra=[]
    if missing:
        run('window_retry','--output',args.output/'retries','--indices',','.join(map(str,missing)))
        extra=['--retries',args.output/'retries']
    run('assemble_window','--primary',args.output/'search',*extra,
        '--output',args.output/'references','--workers',args.workers)
    write(args.output/'COMPLETE.json',dict(passed=True,references=100,original_terminal_oracle=False,
        reference_complete_sha256=sha(args.output/'references/COMPLETE.json'),training_ready=False))


if __name__=='__main__':main()
