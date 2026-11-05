"""Extracted-package integration checks; reuses local Python, no GPU or SSH."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile

from .common import ROOT,identity,snapshot,write,sha


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    args.output=args.output.resolve()
    snapshot(args.output,dict(operation='Extract standalone package, doctor/CPU/subgame/resume/audit/timeout/analysis integration',
        archive=str(args.archive),environment='Uses actual local Python and installed pinned numpy/scipy; no fresh pip install',
        Linux_memory_limit='NOT_TESTED_ON_MACOS',GPU='NOT_USED',remote_server='NOT_ACCESSED'),{'archive':identity(args.archive)})
    parent=Path(tempfile.mkdtemp(prefix='three_player_remote_check_',dir='/private/tmp'))
    with tarfile.open(args.archive) as tar:tar.extractall(parent,filter='data')
    package=parent/'three_player_remote_v1';(args.output/'EXTRACTED_PATH.txt').write_text(str(package)+'\n')
    env=os.environ.copy();env['PYTHONPATH']=str(package)+os.pathsep+str(package/'third_party/negotiation_benchmark/src')
    for k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS'):env[k]='1'
    steps=[]
    def call(name,arguments,expected=0):
        command=[sys.executable,'-m',*arguments]
        completed=subprocess.run(command,cwd=package,env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=120)
        log=args.output/f'{name}.log';log.write_text(completed.stdout)
        ok=completed.returncode==0 if expected==0 else completed.returncode!=0
        steps.append(dict(name=name,command=command,returncode=completed.returncode,expected_success=expected==0,
                          passed=ok,log_sha256=sha(log)))
        write(args.output/'steps.json',steps)
        assert ok,(name,completed.stdout[-3000:])
        return completed
    ns='new.three_player_complexity_v1_20261023'
    call('doctor',[ns+'.remote','doctor'])
    call('cpu',[ns+'.validate','--output','validation/cpu'])
    job='new/three_player_complexity_v1_20261023/diagnostic_jobs_v1/parent25_subgames.jsonl'
    command=[ns+'.remote','run','--jobs',job,'--output','validation/parent25','--workers','1',
        '--max-nodes','10000','--construct-seconds','20','--solve-seconds','15','--audit-seconds','30',
        '--metric-seconds','30','--case-seconds','90','--backend','inertia','--memory-gb','0']
    call('terminal_subgames',command)
    original=sha(package/'validation/parent25/results.json')
    call('resume',command+['--resume','--workers','2'])
    assert sha(package/'validation/parent25/results.json')==original,'Resume changed completed results'
    call('mismatched_resume',command+['--resume','--solve-seconds','16'],expected=1)
    assert sha(package/'validation/parent25/results.json')==original
    call('reload',[ns+'.remote','audit','--run','validation/parent25','--output','validation/reload',
        '--workers','1','--seconds','30','--case-seconds','90','--memory-gb','0'])
    call('hard_timeout',[ns+'.remote','run','--jobs',job,'--output','validation/hard_timeout','--indices','0',
        '--workers','1','--case-seconds','0.001','--memory-gb','0'])
    failed=json.loads((package/'validation/hard_timeout/results.json').read_text())
    assert failed[0]['status']=='hard_wall_timeout' and not failed[0]['reference_accepted']
    # Exercise analysis on a stored full-parent result, without solving its
    # 170835-node tree again. The supplied subset remains clearly one case.
    original_run=ROOT/'new/three_player_complexity_v1_20261023/full_H2_reuse_v1'
    copied=package/'validation/stored_full_H2';copied.mkdir()
    for name in ('results.json','jobs.json','pipeline_snapshot.json'):shutil.copyfile(original_run/name,copied/name)
    call('coverage_analysis',[ns+'.analyse','--run','validation/stored_full_H2',
        '--baseline','data/baseline_three_player.json','--output','validation/analysis'])
    report=json.loads((package/'validation/analysis/ANALYSIS.json').read_text())
    assert report['arms']['H2']['measured']==1
    certificate=json.loads((package/'validation/reload/COMPLETE.json').read_text())
    assert certificate['independently_passed']==2
    result=json.loads((package/'validation/parent25/results.json').read_text())
    assert result[1]['summary']['counterfactual']['max_private_S']>0.16
    write(args.output/'COMPLETE.json',dict(passed=True,steps=len(steps),source_archive_sha256=sha(args.archive),
        parent25_subgames_independently_reloaded=2,strict_resume_unchanged=True,config_mismatch_rejected=True,
        timeout_not_counted_as_certificate=True,coverage_analysis_passed=True,remote_server_tested=False,
        fresh_dependency_install_tested=False,Linux_memory_limit_tested=False,
        steps_sha256=sha(args.output/'steps.json'),pipeline_snapshot_sha256=sha(args.output/'pipeline_snapshot.json')))
    print(dict(passed=True,steps=len(steps),package=str(package)))


if __name__=='__main__':main()
