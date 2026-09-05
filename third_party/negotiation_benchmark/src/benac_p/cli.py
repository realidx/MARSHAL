"""Command-line smoke runner for BENAC-P v0."""

from __future__ import annotations

import argparse
import json
import os

from benac_p.generator import GeneratorConfig, generate_game
from benac_p.oracle import OraclePolicy
from benac_p.policies import RandomPolicy
from benac_p.runner import GameRunner
from benac_p.solver import PerfectInfoSolver


def _parse_device_mapping(value: str) -> list[int]:
    try:
        devices = [int(item.strip()) for item in value.split(",") if item.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("device mapping must be comma-separated integers") from exc
    if not devices or any(device < 0 for device in devices):
        raise argparse.ArgumentTypeError("device mapping must contain at least one non-negative GPU id")
    return devices


def _build_vllm_policies(args: argparse.Namespace, n_players: int):
    try:
        import ray
        from vllm import SamplingParams
        from roll.distributed.scheduler.resource_manager import ResourceManager
        from roll.third_party.vllm import AsyncLLM, LLM
    except ImportError as exc:  # pragma: no cover - depends on optional runtime
        raise RuntimeError(
            "The vLLM self-play command requires Ray, vLLM, and the repository's "
            "ROLL runtime. Use --self-play random for a dependency-free smoke test."
        ) from exc

    from benac_p.vllm_policy import VLLMPlayerPolicy
    from methods.vllm_client import VLLMNegotiationClient

    if not ray.is_initialized():
        ray.init()
    device_mapping = args.device_mapping
    resource_manager = ResourceManager(num_gpus_per_node=len(device_mapping), num_nodes=1)
    placement_groups = resource_manager.allocate_placement_group(
        world_size=1,
        device_mapping=device_mapping,
    )
    sampling_params = SamplingParams(
        temperature=0.0,
        top_p=1.0,
        top_k=-1,
        max_tokens=args.max_tokens,
        n=1,
    )
    model_cls = AsyncLLM if args.async_mode else LLM
    model = model_cls(
        resource_placement_groups=placement_groups[0],
        model=args.vllm_model,
        dtype=args.dtype,
        gpu_memory_utilization=args.gpu_memory_utilization,
        tensor_parallel_size=args.tensor_parallel_size,
        trust_remote_code=True,
        distributed_executor_backend="ray",
        disable_custom_all_reduce=True,
        enforce_eager=True,
        enable_sleep_mode=True,
    )
    client = VLLMNegotiationClient(
        model,
        sampling_params=sampling_params,
        async_mode=args.async_mode,
    )
    return {
        player_id: VLLMPlayerPolicy(client, model=args.vllm_model)
        for player_id in range(n_players)
    }


def _build_oracle_policies(args: argparse.Namespace, spec):
    solver = PerfectInfoSolver(spec, max_states=args.max_solver_states)
    return {
        player_id: OraclePolicy(solver)
        for player_id in range(spec.n_players)
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one BENAC-P v0 self-play episode.")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--self-play", choices=("random", "vllm", "oracle"), default="random")
    parser.add_argument("--observation-mode", choices=("private", "public", "full"), default="private")
    parser.add_argument("--n-rounds", type=int, default=4)
    parser.add_argument("--non-strict", action="store_true")
    parser.add_argument(
        "--vllm-model",
        default=os.environ.get("BENAC_P_VLLM_MODEL", "Qwen/Qwen2.5-7B-Instruct"),
    )
    parser.add_argument("--async-mode", action="store_true")
    parser.add_argument("--device-mapping", type=_parse_device_mapping, default=[0])
    parser.add_argument("--tensor-parallel-size", type=int, default=None)
    parser.add_argument("--dtype", default="bfloat16")
    parser.add_argument("--gpu-memory-utilization", type=float, default=0.8)
    parser.add_argument("--max-tokens", type=int, default=256)
    parser.add_argument(
        "--max-solver-states",
        type=int,
        default=100_000,
        help="Exact-solver state budget for --self-play oracle.",
    )
    parser.add_argument("--json", action="store_true", help="Print the full JSON episode result.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.n_rounds < 1:
        raise SystemExit("--n-rounds must be positive")
    if args.tensor_parallel_size is None:
        args.tensor_parallel_size = len(args.device_mapping)
    if args.tensor_parallel_size != len(args.device_mapping):
        raise SystemExit("--tensor-parallel-size must equal the number of --device-mapping GPUs")

    spec = generate_game(
        seed=args.seed,
        config=GeneratorConfig(n_rounds=args.n_rounds),
    )
    if args.self_play == "random":
        policies = {
            player_id: RandomPolicy(seed=args.seed + player_id)
            for player_id in range(spec.n_players)
        }
    elif args.self_play == "vllm":
        policies = _build_vllm_policies(args, spec.n_players)
    else:
        policies = _build_oracle_policies(args, spec)

    result = GameRunner(
        spec,
        policies,
        observation_mode=args.observation_mode,
        strict=not args.non_strict,
    ).run()
    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(
            f"seed={result.seed} turns={len(result.transcript)} "
            f"goals={sum(result.goal_satisfaction)}/{len(result.goal_satisfaction)} "
            f"rewards={list(result.terminal_rewards)} "
            f"invalid_actions={result.invalid_action_count}"
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
