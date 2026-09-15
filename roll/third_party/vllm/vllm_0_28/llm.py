"""ROLL's synchronous vLLM 0.28 V1 entrypoint.

The public vLLM 0.28 'LLM' constructor already contains the correct V1
renderer, request processor, and output handling. This adapter temporarily
routes that constructor through 'LLMEngine028' and leaves the rest of the
public API intact.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

import vllm.entrypoints.llm as llm_entrypoint
from vllm import LLM as VllmLLM

from .llm_engine import LLMEngine028, WORKER_QUALNAME


logger = logging.getLogger(__name__)


class Llm028(VllmLLM):
    """Use one vLLM V1 worker inside each ROLL inference actor."""

    def __init__(self, resource_placement_groups: list[dict], **kwargs: Any) -> None:
        if resource_placement_groups is None:
            raise ValueError("vLLM 0.28 requires ROLL resource placement metadata")

        tensor_parallel_size = int(kwargs.get("tensor_parallel_size", 1))
        if tensor_parallel_size != 1:
            raise ValueError(
                "vLLM 0.28 ROLL actors must use tensor_parallel_size=1; "
                "allocate TP through ROLL's actor workers instead"
            )

        requested_backend = kwargs.get("distributed_executor_backend")
        if requested_backend not in (None, "uni"):
            logger.warning(
                "vLLM 0.28 ROLL adapter changes distributed_executor_backend=%r "
                "to 'uni': ROLL already pins this actor to one GPU",
                requested_backend,
            )

        kwargs = dict(kwargs)
        kwargs["distributed_executor_backend"] = "uni"
        kwargs["worker_cls"] = WORKER_QUALNAME

        # vLLM's public constructor resolves LLMEngine from a module global.
        # Patch that one call so all normal 0.28 initialization (including
        # renderer/tokenizer setup) remains owned by vLLM itself.
        previous_engine = llm_entrypoint.LLMEngine
        llm_entrypoint.LLMEngine = LLMEngine028
        try:
            super().__init__(**kwargs)
        finally:
            llm_entrypoint.LLMEngine = previous_engine

        self.resource_placement_groups = resource_placement_groups
        self.requested_distributed_executor_backend = requested_backend

    def load_states(self) -> None:
        self.collective_rpc(method="load_states")

    def offload_states(self, level: int = 1) -> None:
        self.reset_prefix_cache()
        self.collective_rpc(method="offload_states", args=(level,))

    def add_requests(
        self,
        prompt_token_ids: list[list[int]],
        request_ids: list[int | str | None],
        sampling_params: Any,
        multi_modal_data: list[Any] | None,
    ) -> None:
        if len(prompt_token_ids) != len(request_ids):
            raise ValueError("prompt_token_ids and request_ids must have equal length")
        if multi_modal_data is not None and len(multi_modal_data) != len(request_ids):
            raise ValueError("multi_modal_data and request_ids must have equal length")
        for index, (token_ids, request_id) in enumerate(zip(prompt_token_ids, request_ids)):
            if request_id is None:
                request_id = next(self.request_counter)
            prompt: dict[str, Any] = {"prompt_token_ids": token_ids}
            if multi_modal_data is not None:
                prompt["multi_modal_data"] = multi_modal_data[index]
            self.llm_engine.add_request(
                request_id=str(request_id), prompt=prompt, params=sampling_params
            )

    def fetch_output(self) -> list[Any]:
        return [output for output in self.llm_engine.step() if output.finished]

    def get_num_waiting(self) -> int:
        return self.llm_engine.get_num_unfinished_requests()

    def clear_unfinished_requests(self) -> None:
        while self.llm_engine.has_unfinished_requests():
            self.llm_engine.step()

    def abort_request(self, request_id: str | Iterable[str]) -> None:
        if isinstance(request_id, str):
            request_ids = [request_id]
        else:
            request_ids = [str(value) for value in request_id]
        self.llm_engine.abort_request(request_ids)

    def setup_collective_group(self, *args: Any, **kwargs: Any) -> None:
        self.collective_rpc(method="setup_collective_group", args=args, kwargs=kwargs)

    def broadcast_bucket(self, src_pp_rank: int, meta_infos: dict, bucket_size: int) -> None:
        # UniProc RPC does not serialize the metadata, so leave meta tensors
        # intact. Worker028 handles dictionary metadata for future RPC paths.
        self.collective_rpc(
            method="broadcast_bucket", args=(src_pp_rank, meta_infos, bucket_size)
        )

    def broadcast_parameter(self, *args: Any, **kwargs: Any) -> None:
        self.collective_rpc(method="broadcast_parameter", args=args, kwargs=kwargs)

    def update_parameter(self, *args: Any, **kwargs: Any) -> None:
        self.collective_rpc(method="update_parameter", args=args, kwargs=kwargs)

    def update_parameter_in_bucket(
        self, meta_infos: dict, buffer: Any, ranks_in_worker: list[int]
    ) -> None:
        self.collective_rpc(
            method="update_parameter_in_bucket",
            args=(meta_infos, buffer, ranks_in_worker),
        )
