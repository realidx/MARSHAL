import os
import shutil
import errno
import uuid

from roll.utils.logging import get_logger


logger = get_logger()

uploader_registry = {}


class FileSystemUploader:
    """
    将本地的ckpt目录上传到文件系统, oss/cpfs在多Role的场景下，
    每个Role会把自己的ckpt dir的内容上传到OUTPUT_DIR/ckpt_id/下
    {
        "type": "file_system",
        "output_dir": /data/oss_bucket_0/llm/models
    }
    """

    def __init__(self, output_dir, *args, use_hardlinks=False, **kwargs):
        self.output_dir = output_dir
        self.use_hardlinks = use_hardlinks
        logger.info(f"use FileSystemUploader to upload {output_dir}")

    def upload(self, ckpt_id: str, local_state_path: str, **kwargs):
        ckpt_id_output_dir = os.path.join(self.output_dir, ckpt_id)
        os.makedirs(ckpt_id_output_dir, exist_ok=True)
        logger.info(f"{local_state_path} save to {ckpt_id_output_dir}, wait...")
        shutil.copytree(local_state_path, ckpt_id_output_dir, dirs_exist_ok=True,
                        copy_function=self._publish_file if self.use_hardlinks else shutil.copy2)
        logger.info(f"{local_state_path} save to {ckpt_id_output_dir}, done...")

    @staticmethod
    def _publish_file(src, dst):
        """Publish completed files atomically; same-filesystem saves avoid a second copy."""
        temporary = str(dst) + ".partial-" + uuid.uuid4().hex
        try:
            try:
                os.link(src, temporary)
            except OSError as exc:
                if exc.errno not in (errno.EXDEV, errno.EPERM, errno.EOPNOTSUPP):
                    raise
                shutil.copy2(src, temporary)
            if os.path.getsize(src) != os.path.getsize(temporary):
                raise IOError(f"Checkpoint size mismatch: {src}")
            os.replace(temporary, dst)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return dst


uploader_registry['file_system'] = FileSystemUploader
