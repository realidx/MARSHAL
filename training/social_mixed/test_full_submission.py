"""Exercise submission wiring with stubbed Slurm/Conda; never submit real jobs."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[2]

class SubmissionTests(unittest.TestCase):
    def run_submission(self, fail_second=False, arm="both"):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);root=Path(tmp.name)
        scripts=root/'examples/social_mixed';scripts.mkdir(parents=True)
        for name in ('start_training.sh','submit_soc.sh'):
            shutil.copyfile(ROOT/'examples/social_mixed'/name,scripts/name)
        conda=root/'conda/etc/profile.d';conda.mkdir(parents=True)
        (conda/'conda.sh').write_text('conda() { return 0; }\n')
        model=root/'model';model.mkdir();(model/'config.json').write_text('{}')
        binary=root/'bin';binary.mkdir()
        python=binary/'python'
        python.write_text(f'#!{sys.executable}\n'+'''import os,sys,json
from pathlib import Path
if '-c' in sys.argv:
    Path(sys.argv[-1]).write_text(json.dumps(dict(kind='stub',commit='test-revision')))
elif 'unittest' in sys.argv or 'training.social_mixed.check_dependencies' in sys.argv:
    print('{}')
else:
    os.execv(sys.executable,[sys.executable]+sys.argv[1:])
''');python.chmod(0o755)
        sbatch=binary/'sbatch'
        sbatch.write_text(f'#!{sys.executable}\n'+'''import os,sys,json
from pathlib import Path
p=Path(os.environ['STUB_CALLS'])
rows=[json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []
record=dict(args=sys.argv[1:],arm=os.environ['SOCIAL_ARM'],seed=os.environ['SOCIAL_SEED'],tokens=os.environ['SOCIAL_TOTAL_TOKENS'],resume=os.environ.get('SOCIAL_RESUME'),diagnose=os.environ.get('SOCIAL_DIAGNOSE_PROBABILITIES'))
with p.open('a') as f:f.write(json.dumps(record)+'\\n')
if os.environ.get('STUB_FAIL_SECOND')=='1' and rows:sys.exit(1)
print(9000+len(rows))
''');sbatch.chmod(0o755)
        env=dict(os.environ,PATH=str(binary)+os.pathsep+os.environ['PATH'],PYTHONPATH=str(ROOT),CONDA_HOME=str(root/'conda'),CONDA_ENV='/stub/env',SOCIAL_MODEL=str(model),SOCIAL_DATA_DIR=str(ROOT/'examples/social_mixed/data_reasoning_v5_candidate'),STUB_CALLS=str(root/'calls.jsonl'),STUB_FAIL_SECOND=str(int(fail_second)),SOCIAL_SEED='123',SOCIAL_DIAGNOSE_PROBABILITIES='1',SOCIAL_RESUME='/bad/old-checkpoint')
        result=subprocess.run(['bash',str(scripts/'start_training.sh'),'h200-141',arm],env=env,text=True,capture_output=True)
        calls=[json.loads(l) for l in (root/'calls.jsonl').read_text().splitlines()]
        receipts=list((root/'submission').glob('*/'+('bp' if arm=='both' else arm)+'.json'))
        self.assertEqual(len(receipts),1,result.stdout+result.stderr)
        return result,calls,receipts[0].parent

    def test_two_full_budget_arms_and_receipts(self):
        result,calls,folder=self.run_submission()
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual([c['arm'] for c in calls],['bp','selfplay'])
        for c in calls:
            self.assertEqual(c['tokens'],'6553600');self.assertEqual(c['seed'],'123')
            self.assertIsNone(c['resume']);self.assertIsNone(c['diagnose'])
            self.assertIn('--gres=gpu:h200-141:1',c['args']);self.assertIn('--parsable',c['args'])
        a=json.loads((folder/'bp.json').read_text());b=json.loads((folder/'selfplay.json').read_text())
        self.assertEqual(a['data_manifest_sha256'],b['data_manifest_sha256'])
        for receipt in (a,b):
            self.assertEqual(receipt['keep_checkpoints'],1)
            self.assertEqual(receipt['dataset'],'data_reasoning_v5_candidate')
            self.assertEqual(receipt['allowed_completion_modes'],['binary','linear'])
        self.assertEqual(a['source_version'],b['source_version'])
        self.assertNotEqual(a['job_id'],b['job_id'])

    def test_bp_only_submits_one_full_budget_job(self):
        result,calls,folder=self.run_submission(arm='bp')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual([c['arm'] for c in calls],['bp'])
        receipt=json.loads((folder/'bp.json').read_text())
        self.assertEqual(receipt['arm'],'bp')
        self.assertEqual(receipt['keep_checkpoints'],1)
        self.assertEqual(receipt['total_tokens'],6553600)
        self.assertFalse((folder/'selfplay.json').exists())

    def test_partial_submission_preserves_first_job_receipt(self):
        result,calls,folder=self.run_submission(fail_second=True)
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(len(calls),2)
        self.assertTrue((folder/'bp.jobid').exists())
        self.assertFalse((folder/'selfplay.json').exists())

if __name__=='__main__':unittest.main()
