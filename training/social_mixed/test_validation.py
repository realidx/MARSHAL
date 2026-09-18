import json
import tempfile
import unittest
from pathlib import Path
from training.social_mixed.core import load_data, seed_for
from training.social_mixed.validation import Validator, VERSION, cells, select_bp, select_resets, persist
from training.social_mixed.test_core import generated
from training.b_sft.social_bp_training import native_completion

class ValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.data=load_data()

    def test_small_fixed_development_panel(self):
        rows=self.data['bp_validation'];tasks=select_bp(rows)
        self.assertEqual(len(tasks),32)
        self.assertEqual(sum(t['task']=='B' for t in tasks),16)
        self.assertEqual(tasks,select_bp(list(reversed(rows))))
        coverage={k for t in tasks for k in cells(t)}
        for k in ['B/full_support','B/reduced_support','P4/query_only','P4/ordinary_action_preferred']:
            self.assertIn(k,coverage)
        for kernel in ['B1','B2','B3','P1','P2','P3','P4']:
            for mode in ['binary','linear']:self.assertIn(kernel+'/'+mode,coverage)
        self.assertEqual(len(select_resets(self.data['selfplay_validation'])),8)
        self.assertEqual(select_resets(self.data['selfplay_validation']),select_resets(list(reversed(self.data['selfplay_validation']))))
        with self.assertRaises(ValueError):select_bp(self.data['bp_train'])

    def test_one_generator_complete_and_failed_games(self):
        answers={seed_for(42,VERSION,'bp',t['id'],0):native_completion(t) for t in select_bp(self.data['bp_validation'])}
        def run(fail):
            def generate(reqs):
                return [dict(completion=answers[r['seed']]) if r['seed'] in answers else generated('PASS',{},'length' if fail else 'stop') for r in reqs]
            return Validator(self.data,generate).run()
        report=run(False)
        self.assertEqual(len(report['bp_calls']),32)
        self.assertEqual(report['metrics']['bp/B/all/correct'],16)
        self.assertEqual(report['metrics']['games/current_team/all/completed'],8)
        failed=run(True)
        self.assertEqual(failed['metrics']['games/current_team/all/completed'],0)
        self.assertNotIn('games/current_team/all/terminal_player_utility_mean',failed['metrics'])
        self.assertTrue(all(g['terminal_utility'] is None for g in failed['games']))
        class Tracker:
            def log(self,metrics,step):self.metrics=metrics;self.step=step
        tracker=Tracker()
        with tempfile.TemporaryDirectory() as root:
            persist(root,report,9,123,tracker)
            saved=json.loads((Path(root)/'validation/step-10.json').read_text())
            self.assertEqual(saved['training_response_tokens'],123)
            self.assertEqual(tracker.step,10)
            self.assertIn('eval/bp/B/all/accuracy',tracker.metrics)

if __name__=='__main__':unittest.main()
