"""Production orchestration invariants, without replacing native oracle tests."""
from collections import Counter
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from training.b_sft.social_private_teacher import PrivateInvestigationRules
from . import freeze as f
from .common import digest

CONFIG = dict(seed=20261003, train=6, validation=3, test=3,
              max_attempts=100, max_per_family=8, three_player_variable_slots=1)


def computed(item, config, sources, cache):
    # Only selection/resume bookkeeping is mocked here; production references
    # and values have separate full native certification and corpus audits.
    return dict(status='qualified', seconds=0, cache_key=digest(item), reason=None,
        diagnostics=[], slices=[dict(parent_id=item['parent_id'], information_positive=True)],
        references={}, world_weights=[1], entrances_sampled=1), cache


class ProductionFreezeTests(unittest.TestCase):
    def test_support_and_parent_identity(self):
        for index in range(16, 46):
            item = f.candidate(index, CONFIG)
            self.assertEqual(item, f.candidate(index, CONFIG))
            raw = dict(item['raw'], slice_setup_histories=[[0]])
            self.assertEqual(f.parent_identity(raw), item['parent_id'])
            if item['players'] == 3:
                self.assertEqual(len(PrivateInvestigationRules(item['raw']).worlds), 3)
        a, b = f.candidate(0, CONFIG), f.candidate(1, CONFIG)
        self.assertEqual(a['family'], b['family'])
        self.assertNotEqual(a['parent_id'], b['parent_id'])

    def test_exact_quota_and_resume_independent_of_worker_count(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(StringIO()):
            root = Path(temp); cache = root / 'cache'
            with patch.object(f, 'cached_candidate', computed):
                first = f.freeze(root / 'first', cache, CONFIG, workers=1)
            def interrupted(item, *args):
                if item['index'] == 21:
                    raise RuntimeError('simulated interruption')
                return computed(item, *args)
            with patch.object(f, 'cached_candidate', interrupted):
                with self.assertRaisesRegex(RuntimeError, 'simulated interruption'):
                    f.freeze(root / 'resumed', cache, CONFIG, workers=4)
            self.assertFalse((root / 'resumed' / 'COMPLETE.json').exists())
            with patch.object(f, 'cached_candidate', computed):
                resumed = f.freeze(root / 'resumed', cache, CONFIG, workers=4)
            self.assertEqual(first['files'], resumed['files'])
            self.assertEqual(resumed['counts'], {
                'train': Counter({2: 4, 3: 2}), 'validation': Counter({2: 2, 3: 1}),
                'test': Counter({2: 2, 3: 1})})

    def test_corrupt_cache_identity_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            cache = Path(temp); sources = f.source_identity(); item = f.candidate(0, CONFIG)
            key = digest(dict(candidate=item, config=CONFIG, source_sha256=sources))
            path = cache / key; path.mkdir()
            f.atomic_json(path / 'result.json', dict(cache_key='tampered', source_sha256=sources))
            with self.assertRaisesRegex(ValueError, 'identity mismatch'):
                f.cached_candidate(item, CONFIG, sources, cache)

    def failure_result(self, exception):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            f.atomic_json(path / 'request.json', dict(candidate=f.candidate(0, CONFIG),
                config=CONFIG, cache_key='test', source_sha256={}))
            with patch.object(f, 'select_bounded_slices', side_effect=exception):
                f.worker(path)
            return json.loads((path / 'result.json').read_text())

    def test_known_numerical_breakdown_has_no_oracle_label(self):
        result = self.failure_result(ValueError(
            'Jacobian inversion yielded zero vector. This indicates a bug in the Jacobian approximation.'))
        self.assertEqual(result['status'], 'excluded')
        self.assertEqual(result['slices'], [])
        self.assertEqual(result['references'], {})
        self.assertIn('Jacobian inversion', result['error'])

    def test_unexpected_valueerror_still_stops_build(self):
        result = self.failure_result(ValueError('invalid probability shape'))
        self.assertEqual(result['status'], 'error')
        self.assertIn('invalid probability shape', result['error'])


if __name__ == '__main__':
    unittest.main()
