"""vLLM 0.28 worker with ROLL's model-update hooks."""

from __future__ import annotations

from typing import Any

import torch
from vllm.v1.worker.gpu_worker import Worker

from roll.third_party.vllm.worker_helper import WorkerHelper
from roll.utils.send_recv_utils import RecvBucketManager


def _restore_meta_dict(meta_infos: Any) -> None:
    """Restore metadata only when an RPC serialized meta tensors to dicts."""

    if not isinstance(meta_infos, dict):
        return
    for meta_info in meta_infos.values():
        if isinstance(meta_info, dict) and isinstance(meta_info.get("tensor_meta"), dict):
            RecvBucketManager.dict_to_meta(meta_infos)
            return


class Worker028(WorkerHelper, Worker):
    """V1 GPU worker extended with ROLL's weight synchronization methods."""

    def broadcast_bucket(self, src_pp_rank: int, meta_infos: dict, bucket_size: int):
        _restore_meta_dict(meta_infos)
        super().broadcast_bucket(src_pp_rank, meta_infos, bucket_size)

    def update_parameter_in_bucket(
        self, meta_infos: dict, buffer: Any, ranks_in_worker: list[int]
    ):
        _restore_meta_dict(meta_infos)
        if not isinstance(buffer, torch.Tensor) or buffer.device.type != "cuda":
            buffer = torch.as_tensor(buffer, dtype=torch.int8, device="cuda")
        elif buffer.dtype != torch.int8:
            buffer = buffer.view(torch.int8)
        super().update_parameter_in_bucket(meta_infos, buffer, ranks_in_worker)
