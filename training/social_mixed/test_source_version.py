import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from training.social_mixed.source_version import verify_source

class SourceTests(unittest.TestCase):
 def test_git_checkout_and_detached_worktree(self):
  with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ):
   os.environ.pop('SOCIAL_SOURCE_COMMIT',None)
   root=Path(tmp)/'repo';root.mkdir()
   def git(*args):return subprocess.check_output(['git','-C',str(root),*args],stderr=subprocess.DEVNULL,text=True).strip()
   git('init');git('-c','user.name=Test','-c','user.email=test@example.org','commit','--allow-empty','-m','test')
   commit=git('rev-parse','HEAD')
   self.assertEqual(verify_source(root)['commit'],commit)
   with patch.dict(os.environ,SOCIAL_SOURCE_COMMIT='wrong'):
    with self.assertRaisesRegex(ValueError,'changed after submission'):verify_source(root)
   (root/'uncommitted.py').write_text('x=1')
   with self.assertRaisesRegex(ValueError,'clean Git checkout'):verify_source(root)
   (root/'uncommitted.py').unlink()
   worktree=Path(tmp)/'worktree';git('worktree','add','--detach',str(worktree),commit)
   self.assertEqual(verify_source(worktree)['commit'],commit)
if __name__=='__main__':unittest.main()
