"""End-to-end scheduling regressions, including real native continuations."""
from argparse import Namespace
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from training.b_sft.social_lm_eval import DryClient, load_pack, run

DATA=Path(__file__).resolve().parents[2]/'new/local_data/social_generalization_v3'


def without_timing(value):
    if isinstance(value,dict):
        return {k:without_timing(v) for k,v in value.items()
                if k not in {'seconds','timings','replay_seconds','worker_pid'}}
    if isinstance(value,list):return [without_timing(v) for v in value]
    return value


@unittest.skipUnless(DATA.exists(),'Requires the local v3 development pack')
class ParallelTests(unittest.TestCase):
    def test_combined_pack_deduplicates_and_retains_membership(self):
        sets={c:{p['row']['id'] for p in load_pack(DATA,c)[1]} for c in ('planning','belief')}
        _,points=load_pack(DATA,'both')
        self.assertEqual(len(points),len(sets['planning']|sets['belief']))
        for p in points:
            self.assertEqual(set(p['cohorts']),{c for c,ids in sets.items() if p['row']['id'] in ids})

    def test_parallel_keeps_scores_calls_and_continuations(self):
        with tempfile.TemporaryDirectory() as temp:
            paths=[]
            for workers in (1,2):
                out=Path(temp)/str(workers);paths.append(out)
                args=Namespace(data_dir=DATA,cohort='both',source=None,limit=4,output_dir=out,
                    dry_run=True,base_urls=None,workers=workers,b_max_tokens=1024,p_max_tokens=768,
                    p_rollouts=2048,p_seconds=20,continue_game=True,roots_only=True,max_worlds=1)
                with redirect_stdout(StringIO()):summary=run(args,DryClient())
                self.assertFalse(summary['errors']);self.assertEqual(summary['failed_points'],0)
                self.assertTrue(summary['fixed']['B_passthrough_all'])
            for filename in ('decisions.jsonl','episodes.jsonl','calls.jsonl','events.jsonl'):
                def rows(path):
                    # Compare all substantive fields, allowing only completion order/timing to differ.
                    return sorted(json.dumps(without_timing(json.loads(l)),sort_keys=True)
                                  for l in (path/filename).read_text().splitlines())
                self.assertEqual(rows(paths[0]),rows(paths[1]),filename)
            pids={json.loads(l)['worker_pid'] for l in (paths[1]/'decisions.jsonl').read_text().splitlines()}
            self.assertEqual(len(pids),2)


if __name__=='__main__':unittest.main()
