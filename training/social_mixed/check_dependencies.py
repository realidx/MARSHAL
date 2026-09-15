"""Check the social-mixed runtime contract without allocating a GPU.

This is deliberately an import/API check. It catches version and adapter
errors before a Slurm job is submitted; model loading, CUDA kernels, and NCCL
still require a separately allocated smoke test.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import inspect
import json
import os
import subprocess
from pathlib import Path
import shutil
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT, ROOT / "mcore_adapter" / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


REQUIRED_DISTRIBUTIONS = (
    "torch",
    "transformers",
    "vllm",
    "ray",
    "megatron-core",
    "transformer-engine",
    "flash-attn",
    "more-itertools",
    "tensordict",
    "codetiming",
    "hydra-core",
    "omegaconf",
    "dacite",
    "accelerate",
    "filelock",
    "huggingface-hub",
    "pydantic",
    "numpy",
)
REQUIRED_MODULES = (
    "megatron.core",
    "transformer_engine.pytorch",
    "flash_attn",
    "vllm.tool_parsers.hermes_tool_parser",
    "mcore_adapter",
    "roll.distributed.strategy.megatron_strategy",
    "roll.distributed.strategy.hf_strategy",
    "roll.distributed.strategy.vllm_strategy",
    "roll.third_party.megatron.offload_states_patch",
    "training.social_mixed.core",
    "training.social_mixed.workers",
    "training.social_mixed.pipeline",
    "training.social_mixed.run",
    "training.b_sft.social_b_grpo",
)
REQUIRED_ENGINE_FIELDS = {
    "model",
    "dtype",
    "tensor_parallel_size",
    "gpu_memory_utilization",
    "max_model_len",
    "max_num_seqs",
    "enforce_eager",
    "enable_sleep_mode",
    "enable_prefix_caching",
    "distributed_executor_backend",
    "load_format",
    "worker_cls",
}


def _version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def check() -> dict[str, Any]:
    result: dict[str, Any] = {
        "gpu_required": False,
        "versions": {name: _version(name) for name in REQUIRED_DISTRIBUTIONS},
        "modules": {},
        "optional_not_required": {
            "deepspeed": "social_mixed uses Megatron for training; the HF reference path does not use DeepSpeed",
            "modelscope": "only needed when MODEL_DOWNLOAD_TYPE=MODELSCOPE; the launcher uses a local model path",
        },
    }
    errors: dict[str, str] = {}

    for name in REQUIRED_DISTRIBUTIONS:
        if result["versions"][name] is None:
            errors[f"distribution:{name}"] = "not installed"

    for name in REQUIRED_MODULES:
        try:
            module = importlib.import_module(name)
            result["modules"][name] = str(getattr(module, "__file__", None))
        except Exception as exc:  # pragma: no cover - exercised by broken envs
            errors[name] = f"{type(exc).__name__}: {exc}"

    pip_check = subprocess.run(
        [sys.executable, "-m", "pip", "check"],
        capture_output=True,
        text=True,
        check=False,
    )
    result["pip_check"] = {
        "returncode": pip_check.returncode,
        "stdout": pip_check.stdout.strip(),
        "stderr": pip_check.stderr.strip(),
    }
    if pip_check.returncode:
        errors["pip_check"] = (pip_check.stdout + pip_check.stderr).strip() or "pip check failed"

    try:
        import vllm
        from vllm import EngineArgs, SamplingParams
        from vllm.entrypoints.llm import LLM as PublicLLM
        from roll.third_party.vllm import LLM as RollLLM
        from roll.third_party.vllm.vllm_0_28.llm_engine import WORKER_QUALNAME
        from roll.third_party.vllm.vllm_0_28.worker import Worker028
        from roll.third_party.vllm.worker_helper import WorkerHelper
        from vllm.tool_parsers.hermes_tool_parser import Hermes2ProToolParser
        from training.b_sft.social_b_grpo import parse_completion

        result["vllm"] = {
            "version": vllm.__version__,
            "roll_adapter": f"{RollLLM.__module__}.{RollLLM.__name__}",
            "worker": WORKER_QUALNAME,
            "public_constructor_patch_point": PublicLLM.__init__.__globals__["LLMEngine"].__module__,
        }
        base_version = vllm.__version__.split("+")[0]
        if base_version != "0.28.0":
            errors["vllm.version"] = f"expected 0.28.0, found {vllm.__version__}"
        if not issubclass(Worker028, WorkerHelper):
            errors["vllm.worker"] = "Worker028 does not include WorkerHelper"

        fields = set(getattr(EngineArgs, "__dataclass_fields__", {}))
        missing_fields = sorted(REQUIRED_ENGINE_FIELDS - fields)
        result["engine_args_fields_checked"] = sorted(REQUIRED_ENGINE_FIELDS)
        if missing_fields:
            errors["vllm.EngineArgs"] = f"missing fields: {missing_fields}"

        SamplingParams(
            n=1,
            temperature=1.0,
            top_p=1.0,
            top_k=-1,
            max_tokens=1,
            logprobs=0,
            seed=0,
        )
        EngineArgs(
            model="/not-loaded-by-preflight",
            dtype="bfloat16",
            tensor_parallel_size=1,
            gpu_memory_utilization=0.65,
            max_model_len=4096,
            max_num_seqs=16,
            enforce_eager=False,
            enable_sleep_mode=True,
            enable_prefix_caching=False,
            distributed_executor_backend="uni",
            load_format="auto",
            worker_cls=WORKER_QUALNAME,
        )
        result["sampling_params"] = "PASS"
        result["engine_args_constructor"] = "PASS"
        result["engine_from_args_signature"] = str(inspect.signature(PublicLLM.from_engine_args))

        # Exercise the adapter's constructor routing without invoking the
        # vLLM engine or loading a model.  This catches a stale backend or
        # worker class before the first GPU allocation.
        captured: dict[str, Any] = {}
        previous_init = PublicLLM.__init__

        def capture_init(self: Any, *args: Any, **kwargs: Any) -> None:
            captured.update(kwargs)

        PublicLLM.__init__ = capture_init
        try:
            RollLLM(
                resource_placement_groups=[{"node_rank": 0, "gpu_rank": 0}],
                model="/not-loaded-by-preflight",
                tensor_parallel_size=1,
                distributed_executor_backend="ray",
            )
        finally:
            PublicLLM.__init__ = previous_init
        if captured.get("distributed_executor_backend") != "uni":
            errors["vllm.adapter_backend"] = "adapter did not force distributed_executor_backend=uni"
        if captured.get("worker_cls") != WORKER_QUALNAME:
            errors["vllm.adapter_worker"] = "adapter did not install the vLLM 0.28 Worker028"
        if not errors.get("vllm.adapter_backend") and not errors.get("vllm.adapter_worker"):
            result["vllm_adapter_constructor"] = "PASS"

        parser = Hermes2ProToolParser(object())
        parsed = parse_completion(parser, "plain response", [])
        if parsed["raw_message"]["content"] != "plain response":
            errors["vllm.hermes_parser"] = "Hermes parser round-trip changed plain response content"
        else:
            result["hermes_parser"] = "PASS"
    except Exception as exc:  # pragma: no cover - exercised by broken envs
        errors["vllm.roll_adapter"] = f"{type(exc).__name__}: {exc}"

    ninja = shutil.which("ninja")
    if ninja is None:
        env_ninja = Path(sys.executable).with_name("ninja")
        if env_ninja.is_file():
            ninja = str(env_ninja)
    if ninja is None:
        errors["ninja"] = "ninja executable is not on PATH"
    else:
        result["ninja"] = ninja

    try:
        from training.b_sft.bp_megatron import validate_environment

        result["megatron_contract"] = validate_environment()
    except Exception as exc:  # pragma: no cover - exercised by broken envs
        errors["megatron_contract"] = f"{type(exc).__name__}: {exc}"

    try:
        os.environ.setdefault("SOCIAL_MODEL", "/not-loaded-by-preflight")
        os.environ.setdefault("ROLL_OUTPUT_DIR", str(ROOT / "output" / "dependency-preflight"))
        os.environ.setdefault("ROLL_LOG_DIR", str(ROOT / "output" / "dependency-preflight" / "logs"))
        from training.social_mixed.run import configuration

        configs = {}
        for arm in ("mixed", "selfplay"):
            config, _ = configuration(arm, seed=0)
            configs[arm] = {
                "actor_train": config.actor_train.strategy_args.strategy_name,
                "actor_infer": config.actor_infer.strategy_args.strategy_name,
                "reference": config.reference.strategy_args.strategy_name,
                "world_sizes": {
                    "actor_train": config.actor_train.world_size,
                    "actor_infer": config.actor_infer.world_size,
                    "reference": config.reference.world_size,
                },
            }
            expected = {
                "actor_train": "megatron_train",
                "actor_infer": "vllm",
                "reference": "hf_infer",
            }
            if any(configs[arm][key] != value for key, value in expected.items()):
                errors[f"config:{arm}"] = f"unexpected strategy selection: {configs[arm]}"
        result["configs"] = configs
    except Exception as exc:  # pragma: no cover - exercised by broken envs
        errors["social_mixed.configuration"] = f"{type(exc).__name__}: {exc}"

    result["errors"] = errors
    result["status"] = "PASS" if not errors else "FAIL"
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    args = parser.parse_args()
    del args
    result = check()
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
