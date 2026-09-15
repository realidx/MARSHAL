"""Small vLLM 0.28 engine shim used by ROLL's per-actor inference workers."""

from __future__ import annotations

from typing import Any

import vllm.envs as envs
from vllm.usage.usage_lib import UsageContext
from vllm.v1.engine.llm_engine import LLMEngine
from vllm.v1.executor import Executor


WORKER_QUALNAME = "roll.third_party.vllm.vllm_0_28.worker.Worker028"


class LLMEngine028(LLMEngine):
    """Create one V1 worker in the ROLL actor that already owns one GPU.

    ROLL creates one actor per inference GPU and passes each actor a placement
    group. The old adapter then asked vLLM to create another Ray worker pool,
    which is incompatible with vLLM 0.28's placement-group validation and can
    accidentally consume the other half of a sliced GPU allocation. The
    actor-local 'uni' executor keeps ownership with ROLL and still exposes
    vLLM's normal V1 engine API.
    """

    @classmethod
    def from_engine_args(
        cls,
        engine_args: Any,
        usage_context: UsageContext = UsageContext.ENGINE_CONTEXT,
        stat_loggers: list[Any] | None = None,
        enable_multiprocessing: bool = False,
    ) -> "LLMEngine028":
        tensor_parallel_size = int(getattr(engine_args, "tensor_parallel_size", 1))
        pipeline_parallel_size = int(getattr(engine_args, "pipeline_parallel_size", 1))
        data_parallel_size = int(getattr(engine_args, "data_parallel_size", 1))
        if tensor_parallel_size != 1 or pipeline_parallel_size != 1 or data_parallel_size != 1:
            raise ValueError(
                "ROLL's vLLM 0.28 adapter expects one TP=1/PP=1/DP=1 engine "
                "inside each ROLL inference actor"
            )

        # The ROLL actor is already pinned to one GPU. In particular, do not
        # let vLLM's Ray executor reinterpret ROLL's single bundle containing
        # the whole actor allocation.
        engine_args.distributed_executor_backend = "uni"
        engine_args.worker_cls = WORKER_QUALNAME
        vllm_config = engine_args.create_engine_config(usage_context)
        executor_class = Executor.get_class(vllm_config)

        # Keep this engine in-process even if a site-wide env var requests the
        # V1 multiprocessing mode. ROLL owns the process boundary and the
        # worker must see the actor's CUDA visibility unchanged.
        if envs.VLLM_ENABLE_V1_MULTIPROCESSING:
            enable_multiprocessing = False

        return cls(
            vllm_config=vllm_config,
            executor_class=executor_class,
            log_stats=not engine_args.disable_log_stats,
            usage_context=usage_context,
            stat_loggers=stat_loggers,
            multiprocess_mode=enable_multiprocessing,
        )
