"""The self-play stage must not run BP postprocessing after collection."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from training.social_mixed import current_train_probe as module
class StageDispatchTests(unittest.TestCase):
 def test_selfplay_finishes_without_bp_file(self):
  with tempfile.TemporaryDirectory() as d:
   argv=['probe','--stage','sp','--learner-url','http://unused','--opponent-url','http://unused','--output',d]
   with patch.object(sys,'argv',argv),patch.object(module.selfplay_probe,'load'),patch.object(module.selfplay_probe,'main') as run:
    module.main()
    run.assert_called_once()
    self.assertFalse((Path(d)/'bp.jsonl').exists())
if __name__=='__main__':unittest.main()
