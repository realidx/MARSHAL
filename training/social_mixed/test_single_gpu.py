"""CPU regression for single-H200 submission, checkpoints and resume guard."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile
from training.b_sft.bp_megatron import complete_checkpoint
from training.social_mixed.run import validate_resume

class SingleGPUChecks(unittest.TestCase):
 def test_submit_requests_one_h200_and_two_h100(self):
  with tempfile.TemporaryDirectory() as tmp:
   binary=Path(tmp)/'sbatch'
   binary.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n');binary.chmod(0o755)
   for profile,count in [('h200-141',1),('h100-96',2)]:
    result=subprocess.run(['bash','examples/social_mixed/submit_soc.sh',profile,'mixed'],env=dict(os.environ,PATH=tmp+':'+os.environ['PATH']),text=True,capture_output=True,check=True)
    self.assertIn(f'--gres=gpu:{profile}:{count}',result.stdout)
 def test_one_rank_native_checkpoint_and_missing_shard(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)
   names=['mca_config.json','latest_checkpointed_iteration.txt','tokenizer.json','tokenizer_config.json','scheduler.pt','pipeline/worker_state_pipeline.json','pipeline/rng_state_pipeline.pth','iter_0000001/mp_rank_00/model_optim_rng.pt','rng_state/rng_state_0.pth','iter_0000001/dist_optimizer/common.pt','iter_0000001/dist_optimizer/.metadata','iter_0000001/dist_optimizer/metadata.json','iter_0000001/dist_optimizer/one.distcp']
   for name in names:
    p=root/name;p.parent.mkdir(parents=True,exist_ok=True)
    if p.suffix in ('.pt','.pth'):
     with zipfile.ZipFile(p,'w') as archive:archive.writestr('placeholder','test')
    else:p.write_text('1')
   self.assertEqual(complete_checkpoint(root,1,10)['tp'],1)
   (root/'iter_0000001/mp_rank_00/model_optim_rng.pt').unlink()
   with self.assertRaises(RuntimeError):complete_checkpoint(root,1,10)
   self.assertFalse((root/'COMPLETE.json').exists())
 def test_reject_cross_tp_resume_before_loading_experiment(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'COMPLETE.json').write_text(json.dumps(dict(tp=2,world_size=2)))
   with self.assertRaisesRegex(ValueError,'same TP/world size'):
    validate_resume(root,dict(gpu_profile='h200-141'),'/unused')
if __name__=='__main__':unittest.main()
