import vllm

LLM = None
AsyncLLM = None

if "0.7.3" in vllm.__version__:
    from roll.third_party.vllm.vllm_0_7_3.llm import Llm073
    LLM = Llm073
elif "0.8.4" in vllm.__version__:
    from roll.third_party.vllm.vllm_0_8_4.llm import Llm084
    from roll.third_party.vllm.vllm_0_8_4.v1.async_llm import AsyncLLM084
    LLM = Llm084
    AsyncLLM = AsyncLLM084
elif vllm.__version__.split("+")[0] in ("0.8.5", "0.8.5.post1"):
    # The V0 EngineArgs/processed-request/worker RPC interfaces are shared
    # with 0.8.4. V1 is deliberately not covered by this compatibility path.
    from vllm import envs
    if envs.VLLM_USE_V1:
        raise NotImplementedError("ROLL vLLM 0.8.5 adapter requires VLLM_USE_V1=0")
    from roll.third_party.vllm.vllm_0_8_4.llm import Llm084
    LLM = Llm084
elif vllm.__version__.split("+")[0] == "0.28.0":
    # vLLM 0.28 is V1-only. It has neither the old V0 worker modules nor
    # VLLM_USE_V1, so it needs its own adapter instead of the 0.8.x path.
    from roll.third_party.vllm.vllm_0_28.llm import Llm028

    LLM = Llm028
else:
    raise NotImplementedError(f"roll vllm version {vllm.__version__} is not supported.")

__all__ = ["LLM", "AsyncLLM"]
