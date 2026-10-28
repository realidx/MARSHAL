import argparse
from pathlib import Path
import unittest
from .common import snapshot,write,sha


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    snapshot(args.output,dict(operation='CPU semantic tests on99 geometry/visibility expansions and omission solver',
        modules=['new.three_player_complexity_v1_20261023.test_study','new.node_qs_audit_v1_20261023.test_metrics',
            'new.node_qs_audit_v1_20261023.test_witness'],GPU=False,training=False))
    suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(name) for name in
        ('new.three_player_complexity_v1_20261023.test_study','new.node_qs_audit_v1_20261023.test_metrics',
         'new.node_qs_audit_v1_20261023.test_witness'))
    with (args.output/'tests.txt').open('w') as stream:result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    write(args.output/'COMPLETE.json',dict(tests=result.testsRun,passed=result.wasSuccessful(),
        log_sha256=sha(args.output/'tests.txt'),pipeline_snapshot_sha256=sha(args.output/'pipeline_snapshot.json')))
    print((args.output/'tests.txt').read_text())
    if not result.wasSuccessful():raise SystemExit(1)


if __name__=='__main__':main()
