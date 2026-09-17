import tempfile
from pathlib import Path
import unittest
from training.social_mixed.checkpoints import prune

class RetentionTests(unittest.TestCase):
    def test_keep_one_preserves_latest_complete_and_incomplete_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for step in (9,19,29):
                for group in ('checkpoints','pipeline','actor_train-0','actor_train-1'):
                    p=root/group/f'checkpoint-{step}';p.mkdir(parents=True)
                if step!=29:(root/'checkpoints'/f'checkpoint-{step}'/'COMPLETE.json').write_text('{}')
            self.assertEqual(prune(root,1),[9])
            self.assertTrue((root/'checkpoints/checkpoint-19/COMPLETE.json').exists())
            self.assertTrue((root/'checkpoints/checkpoint-29').exists())
            for group in ('checkpoints','pipeline','actor_train-0','actor_train-1'):
                self.assertFalse((root/group/'checkpoint-9').exists())
            (root/'checkpoints/checkpoint-29/COMPLETE.json').write_text('{}')
            self.assertEqual(prune(root,1),[19])
            self.assertTrue((root/'checkpoints/checkpoint-29/COMPLETE.json').exists())

if __name__=='__main__':unittest.main()
