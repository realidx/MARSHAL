"""Real Hydra + dacite + RLVRConfig construction, no Ray/vLLM/model imports."""
import logging
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
import unittest
from unittest.mock import patch
from training.social_mixed.run import configuration
from training.social_mixed.hardware import PROFILES


@contextmanager
def temporary_configuration_dir():
 with tempfile.TemporaryDirectory() as root:
  try:
   yield root
  finally:
   # The test temp directory is on NFS; close ROLL's file handler before
   # cleanup so an open .nfs* file cannot make rmtree fail.
   from roll.utils import logging as roll_logging
   if roll_logging.logger is not None:
    for handler in roll_logging.logger.handlers[:]:
     if isinstance(handler, logging.FileHandler):
      roll_logging.logger.removeHandler(handler)
      handler.close()
   roll_logging.logger_log_dir = None


class ConfigurationTests(unittest.TestCase):
 def test_all_profiles_and_arms_preserve_optimizer_step_budget(self):
  with temporary_configuration_dir() as root:
   for profile,expected in PROFILES.items():
    for arm in ('mixed','selfplay'):
     with self.subTest(profile=profile,arm=arm),patch.dict(os.environ,SOCIAL_GPU_PROFILE=profile,SOCIAL_MODEL='/not-loaded',ROLL_OUTPUT_DIR=root,ROLL_LOG_DIR=root+'/logs',PYTHONPATH=os.getcwd()):
      cfg,resolved=configuration(arm)
      self.assertTrue(cfg.actor_infer.strategy_args.strategy_config['enforce_eager'])
      self.assertEqual(cfg.actor_train.system_envs['CUDNN_FRONTEND_CUDART_LIB_NAME'],'libcudart.so.13')
      self.assertEqual(cfg.actor_infer.system_envs['CUDNN_FRONTEND_CUDART_LIB_NAME'],'libcudart.so.13')
      self.assertEqual(cfg.max_steps,1000)
      self.assertEqual(cfg.actor_train.training_args.max_steps,1000)
      self.assertEqual(resolved['actor_train']['training_args']['max_steps'],1000)
      self.assertEqual(cfg.actor_train.training_args.per_device_train_batch_size,expected['train_microbatch'])
      self.assertEqual(cfg.actor_train.world_size,expected['gpus'])
      self.assertEqual(cfg.actor_infer.world_size,expected['gpus'])
      self.assertEqual(cfg.reference.world_size,expected['gpus'])
      self.assertEqual(cfg.actor_train.strategy_args.strategy_config['tensor_model_parallel_size'],expected['tp'])
      self.assertEqual(cfg.actor_train.strategy_args.strategy_config['sequence_parallel'],expected['tp']>1)
      self.assertEqual(cfg.num_gpus_per_node,expected['gpus'])
      self.assertEqual(cfg.actor_train.strategy_args.strategy_config['pipeline_model_parallel_size'],1)
      self.assertEqual(cfg.actor_train.training_args.learning_rate,1e-6)
      self.assertEqual(cfg.actor_infer.generating_args.max_new_tokens,1024)
 def test_resume_does_not_reintroduce_generic_step_conversion(self):
  with temporary_configuration_dir() as root,patch.dict(os.environ,SOCIAL_GPU_PROFILE='h200-141',SOCIAL_MODEL='/not-loaded',ROLL_OUTPUT_DIR='/tmp/social-test-output',ROLL_LOG_DIR='/tmp/social-test-logs',PYTHONPATH=os.getcwd()):
   cfg,resolved=configuration('mixed',resume=root)
   self.assertEqual(cfg.actor_train.training_args.max_steps,1000)
   self.assertEqual(cfg.resume_from_checkpoint,str(Path(root).resolve()))
if __name__=='__main__':unittest.main()
