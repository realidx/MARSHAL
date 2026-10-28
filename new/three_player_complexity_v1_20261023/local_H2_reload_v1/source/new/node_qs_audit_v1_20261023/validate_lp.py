import argparse
from pathlib import Path
import unittest
from .run import snapshot
from new.sparse_solver_v1_20261023.common import write,sha


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();snapshot(args.output,dict(operation='Omission/recall and independent LP tie-bound CPU tests',
        tests=['test_metrics','test_witness'],GPU=False,model=False,training=False),{})
    suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(name) for name in
        ('new.node_qs_audit_v1_20261023.test_metrics','new.node_qs_audit_v1_20261023.test_witness'))
    with (args.output/'tests.txt').open('w') as stream:
        result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    write(args.output/'COMPLETE.json',dict(tests=result.testsRun,passed=result.wasSuccessful(),
        failures=len(result.failures),errors=len(result.errors),test_log_sha256=sha(args.output/'tests.txt'),
        snapshot_sha256=sha(args.output/'pipeline_snapshot.json')))
    print((args.output/'tests.txt').read_text())
    if not result.wasSuccessful():raise SystemExit(1)


if __name__=='__main__':main()
