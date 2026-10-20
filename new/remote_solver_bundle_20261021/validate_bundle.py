"""Exercise the final handoff archive outside the repository, on CPU only."""
from hashlib import sha256
import json
from pathlib import Path
import signal
import subprocess
import sys
import tarfile
import tempfile
import time

HERE=Path(__file__).resolve().parent
OUT=HERE/'validation';OUT.mkdir(exist_ok=False)
TMP=Path(tempfile.mkdtemp(prefix='marshal-remote-final-'))
ARCHIVE=HERE/'game_oracle_remote_v1.tar.gz'
with tarfile.open(ARCHIVE) as tar:tar.extractall(TMP,filter='data')
WD=TMP/'game_oracle_remote_v1'
MODULE='new.strategic_game_v1_20261021.remote_solver'
commands=[];checks={}


def run(label,args,expected=0):
    start=time.monotonic()
    command=[sys.executable,*args]
    with (OUT/(label+'.log')).open('x') as log:
        result=subprocess.run(command,cwd=WD,stdout=log,stderr=subprocess.STDOUT,timeout=180,
            env={**__import__('os').environ,'PYTHONPATH':str(WD)+':'+str(WD/'third_party/negotiation_benchmark/src')})
    commands.append(dict(label=label,argv=command,returncode=result.returncode,
        expected=expected,seconds=time.monotonic()-start))
    if result.returncode!=expected:raise AssertionError(label+': '+(OUT/(label+'.log')).read_text()[-4000:])


def cli(label,args,expected=0):run(label,['-m',MODULE,*args],expected)


def obj(path):return json.loads((WD/path).read_text())


base=['run','--output','remote_runs/smoke','--profile','base','--workers','1','--indices','0',
      '--construct-seconds','30','--solve-seconds','60','--audit-seconds','60']
cli('doctor',['doctor'])
run('six_semantic_checks',['-m','unittest','new.strategic_game_v1_20261021.test_rules',
    'new.game_design_feasibility_20261021.test_design','-v'])
checks['six_semantic_tests']=True
cli('one_parent_real_solve',base)
summary=obj('remote_runs/smoke/summary.json')
assert summary['counts']=={'certified':1} and not summary['all_100_certified']
r=summary['results'][0];ref=WD/'remote_runs/smoke'/r['execution']/'reference.npz'
ref_hash=sha256(ref.read_bytes()).hexdigest();ref_mtime=ref.stat().st_mtime_ns
cli('closed_resume',base+['--resume'])
assert sha256(ref.read_bytes()).hexdigest()==ref_hash and ref.stat().st_mtime_ns==ref_mtime
checks['completed_reference_reused_without_rewrite']=True
cli('reload_and_full_recertification',['audit','--output','remote_runs/smoke','--seconds','60'])
checks['saved_npz_reloaded_full_terminal_recertification']=True
cli('import_certified_reference',['run','--output','remote_runs/imported','--profile','extended',
    '--workers','1','--indices','0','--from-run','remote_runs/smoke'])
imported=obj('remote_runs/imported/summary.json')['results'][0]
assert imported['origin']=='imported' and imported['reference_sha256']==ref_hash
cli('imported_profile_full_recertification',['audit','--output','remote_runs/imported','--seconds','60'])
checks['import_preserves_reference_and_original_constructor_identity']=True

fail=['run','--output','remote_runs/failed','--profile','base','--workers','1','--indices','0',
      '--construct-seconds','30','--solve-seconds','0.001','--audit-seconds','30']
cli('forced_budget_failure',fail)
assert obj('remote_runs/failed/summary.json')['counts']=={'unavailable':1}
cli('all_declared_retry_starts',['run','--output','remote_runs/all_retry_failed','--profile','extended',
    '--workers','1','--indices','0','--from-run','remote_runs/failed',
    '--construct-seconds','30','--solve-seconds','0.001','--audit-seconds','30'])
attempts=sorted((WD/'remote_runs/all_retry_failed/attempts').glob('*/plan-*/execution-*/result.json'))
assert [json.loads(p.read_text())['plan']['start'] for p in attempts]==['uniform','dirichlet:0','dirichlet:1','dirichlet:2']
assert all(json.loads(p.read_text())['status']=='unavailable' for p in attempts)
checks['failure_is_missing_and_four_retry_starts_exhaust_in_order']=True

cancel=['run','--output','remote_runs/cancelled','--profile','base','--workers','1','--indices','0',
        '--construct-seconds','30','--solve-seconds','2','--audit-seconds','30']
with (OUT/'cancellation.log').open('x') as log:
    proc=subprocess.Popen([sys.executable,'-m',MODULE,*cancel],cwd=WD,stdout=log,stderr=subprocess.STDOUT)
    deadline=time.monotonic()+20
    while not list((WD/'remote_runs/cancelled').glob('attempts/*/plan-*/execution-*/worker.log')):
        if time.monotonic()>deadline or proc.poll() is not None:raise AssertionError('No cancellable worker launched')
        time.sleep(.02)
    proc.send_signal(signal.SIGTERM)
    assert proc.wait(timeout=20)==130
assert not (WD/'remote_runs/cancelled/COMPLETE.json').exists()
assert not (WD/'remote_runs/cancelled/.run.lock').exists()
cli('resume_after_sigterm',cancel+['--resume'])
executions=list((WD/'remote_runs/cancelled').glob('attempts/*/plan-*/execution-*'))
assert len(executions)==2
states=[json.loads(p.read_text())['status'] for p in (WD/'remote_runs/cancelled/sessions').glob('*.json')]
assert 'interrupted' in states and 'finished' in states
checks['sigterm_preserves_partial_execution_and_resume_creates_new_execution']=True

cli('retry_failed_parent_until_certified',['run','--output','remote_runs/recovered','--profile','extended',
    '--workers','1','--indices','0','--from-run','remote_runs/failed',
    '--construct-seconds','30','--solve-seconds','60','--audit-seconds','60'])
assert obj('remote_runs/recovered/summary.json')['counts']=={'certified':1}
assert len(list((WD/'remote_runs/recovered').glob('attempts/*/plan-*/execution-*')))==1
checks['first_certified_retry_stops_further_starts']=True

cli('resume_parameter_change_rejected',[x if x!='base' else 'extended' for x in base]+['--resume'],1)
checks['changed_resume_contract_rejected']=True
cli('scope_one_not_claimed_as_all_100',['audit','--output','remote_runs/smoke','--hash-only','--require-all'],2)
checks['one_parent_smoke_never_claimed_as_100_complete']=True

original=ref.read_bytes()
try:
    ref.write_bytes(original[:-1]+bytes([original[-1]^1]))
    cli('reference_corruption_rejected',['audit','--output','remote_runs/smoke','--hash-only'],1)
finally:ref.write_bytes(original)
checks['reference_corruption_rejected']=True
data=WD/'new/strategic_game_v1_20261021/parents_100_v1/parents.jsonl'
original=data.read_bytes()
try:
    data.write_bytes(original+b'\n')
    cli('changed_input_rejected',['doctor'],1)
finally:data.write_bytes(original)
checks['changed_parent_data_rejected']=True
cli('final_integrity',['audit','--output','remote_runs/smoke','--hash-only'])

result=dict(status='PASS',archive_sha256=sha256(ARCHIVE.read_bytes()).hexdigest(),
    bundle_manifest_sha256=sha256((WD/'BUNDLE_MANIFEST.json').read_bytes()).hexdigest(),
    validation_script_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
    source_files=json.loads((WD/'BUNDLE_MANIFEST.json').read_text())['files'],
    temp_extraction=str(WD),checks=checks,commands=commands,
    scope='Local CPU only; one real parent for solver/interface integration, six semantic tests; not 100-parent remote performance or model training evidence',
    remote_linux_slurm_execution='NOT_RUN',GPU='NOT_RUN',model_D='NOT_MEASURED')
(HERE/'VALIDATION.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(dict(status=result['status'],checks=len(checks),evidence=str(HERE/'VALIDATION.json'))))
