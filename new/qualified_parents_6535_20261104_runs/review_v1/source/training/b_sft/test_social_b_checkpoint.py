"""CPU-only checks for atomic publication, failure propagation and completeness."""
import errno
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from roll.utils.upload_utils import FileSystemUploader
from roll.utils.checkpoint_manager import CheckpointManager
from roll.utils.checkpoint_integrity import complete_deepspeed_checkpoint


class CheckpointTests(unittest.TestCase):
    def test_publication_survives_source_removal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / 'source'; source.mkdir()
            (source / 'weights').write_bytes(b'complete tensor')
            manager = CheckpointManager(dict(type='file_system', output_dir=str(root/'dest'),
                                            use_hardlinks=True, raise_on_error=True))
            manager.upload('checkpoint-1', str(source))
            self.assertFalse(source.exists())
            self.assertEqual((root/'dest/checkpoint-1/weights').read_bytes(), b'complete tensor')

    def test_failure_propagates_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)/'source'; source.mkdir(); (source/'weights').write_bytes(b'old')
            manager = CheckpointManager(dict(type='file_system', output_dir=tmp+'/dest',
                                            use_hardlinks=True, raise_on_error=True))
            with patch('roll.utils.upload_utils.os.link', side_effect=OSError(errno.ENOSPC, 'full')):
                with self.assertRaises(Exception):
                    manager.upload('checkpoint-1', str(source))
            self.assertTrue((source/'weights').exists())

    def test_cross_device_copy_is_atomic(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp)/'src'; dst = Path(tmp)/'dst'
            src.write_bytes(b'new'); dst.write_bytes(b'old')
            with patch('roll.utils.upload_utils.os.link', side_effect=OSError(errno.EXDEV, 'cross device')):
                FileSystemUploader._publish_file(src, dst)
            self.assertEqual(dst.read_bytes(), b'new')
            self.assertEqual(list(Path(tmp).glob('*.partial-*')), [])

    def test_zero2_all_ranks_required_and_truncation_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'checkpoint').mkdir(); (root/'pipeline').mkdir()
            (root/'config.json').write_text('{}')
            (root/'tokenizer_config.json').write_text('{}')
            (root/'tokenizer.json').write_text('{}')
            (root/'pipeline/worker_state_pipeline.json').write_text('{}')
            names=['pytorch_model.bin', 'checkpoint/mp_rank_00_model_states.pt', 'pipeline/rng_state_pipeline.pth']
            names += [f'checkpoint/bf16_zero_pp_rank_{rank}_mp_rank_00_optim_states.pt' for rank in range(4)]
            for name in names[:-1]:
                with zipfile.ZipFile(root/name,'w') as archive: archive.writestr('data',b'tensor')
            with self.assertRaises(RuntimeError): complete_deepspeed_checkpoint(root,4,59)
            self.assertFalse((root/'COMPLETE.json').exists())
            (root/names[-1]).write_bytes(b'truncated')
            with self.assertRaises(zipfile.BadZipFile): complete_deepspeed_checkpoint(root,4,59)
            with zipfile.ZipFile(root/names[-1],'w') as archive: archive.writestr('data',b'tensor')
            complete_deepspeed_checkpoint(root,4,59)
            self.assertEqual(json.loads((root/'COMPLETE.json').read_text())['world_size'],4)


if __name__ == '__main__': unittest.main()
