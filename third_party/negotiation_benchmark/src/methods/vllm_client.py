"""Adapters for using vLLM engines and servers with the benchmark.

The benchmark only needs a small text-generation interface.  This module
keeps the benchmark independent of the vLLM import at module-load time.  It
supports the synchronous and asynchronous engines exposed by
``roll.third_party.vllm`` as well as the OpenAI-compatible HTTP API exposed by
newer vLLM servers.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import urllib.error
import urllib.request
from typing import Any, Mapping, Sequence
from uuid import uuid4


class VLLMNegotiationClient:
    """Text-generation adapter for a vLLM ``LLM`` or ``AsyncLLM`` instance.

    Args:
        model: A synchronous vLLM model, an asynchronous vLLM model, or an
            initialized ROLL ``VllmStrategy``.  For a strategy, its underlying
            ``model`` and ``tokenizer`` are used.
        tokenizer: Optional tokenizer.  Supplying it is recommended for an
            ``AsyncLLM`` instance because that engine exposes an async
            tokenizer accessor.
        sampling_params: A vLLM ``SamplingParams`` object.  When omitted, a
            deterministic JSON-friendly configuration is created.
        async_mode: Set to ``True`` for ROLL's ``AsyncLLM``.  If omitted, the
            adapter uses the synchronous ``generate(prompts=[...])`` API.
        max_tokens: Used only when ``sampling_params`` is omitted.
    """

    def __init__(
        self,
        model: Any,
        *,
        tokenizer: Any | None = None,
        sampling_params: Any | None = None,
        async_mode: bool = False,
        max_tokens: int = 512,
    ) -> None:
        strategy = getattr(model, "model", None)
        if strategy is not None and not hasattr(model, "llm_engine"):
            # This supports an initialized ROLL VllmStrategy without importing
            # the strategy class (which would pull in Ray and torch).
            if tokenizer is None:
                tokenizer = getattr(model, "tokenizer", None)
            model = strategy

        if model is None or not hasattr(model, "generate"):
            raise TypeError(
                "model must be an initialized vLLM LLM/AsyncLLM instance "
                "or an initialized ROLL VllmStrategy."
            )

        self.model = model
        self.async_mode = async_mode
        self.tokenizer = tokenizer or self._get_tokenizer(model)
        self.sampling_params = sampling_params or self._default_sampling_params(
            max_tokens=max_tokens
        )

    @staticmethod
    def _get_tokenizer(model: Any) -> Any | None:
        """Resolve a tokenizer from a sync or async vLLM engine."""
        get_tokenizer = getattr(model, "get_tokenizer", None)
        if get_tokenizer is None:
            return None

        tokenizer = get_tokenizer()
        if inspect.isawaitable(tokenizer):
            return _run_coroutine(tokenizer)
        return tokenizer

    @staticmethod
    def _default_sampling_params(*, max_tokens: int) -> Any:
        """Create deterministic sampling parameters without a hard import."""
        try:
            from vllm import SamplingParams
        except ImportError as exc:  # pragma: no cover - exercised with vLLM installed
            raise ImportError(
                "vLLM is required when sampling_params is not supplied. "
                "Pass an existing vLLM SamplingParams object or install vLLM."
            ) from exc

        return SamplingParams(
            temperature=0.0,
            top_p=1.0,
            top_k=-1,
            max_tokens=max_tokens,
            n=1,
        )

    def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        response_format: Mapping[str, Any] | None = None,
        model: str | None = None,
    ) -> str:
        """Generate one assistant response from OpenAI-style messages.

        ``response_format`` and ``model`` are accepted for compatibility with
        the benchmark's OpenAI client protocol.  vLLM receives the JSON
        requirement through the prompt itself.
        """
        del response_format, model
        prompt = self.render_messages(messages)

        if self.async_mode:
            return _run_coroutine(self._complete_async(prompt))

        outputs = self.model.generate(
            prompts=[prompt],
            sampling_params=self.sampling_params,
            use_tqdm=False,
        )
        return self._extract_text(outputs)

    def render_messages(self, messages: Sequence[Mapping[str, str]]) -> str:
        """Render chat messages using the model tokenizer when available."""
        normalized = [
            {"role": str(message["role"]), "content": str(message["content"])}
            for message in messages
        ]

        apply_chat_template = getattr(self.tokenizer, "apply_chat_template", None)
        if apply_chat_template is not None:
            return apply_chat_template(
                normalized,
                tokenize=False,
                add_generation_prompt=True,
            )

        chunks = []
        for message in normalized:
            chunks.append(
                f"<|im_start|>{message['role']}\n"
                f"{message['content']}<|im_end|>\n"
            )
        chunks.append("<|im_start|>assistant\n")
        return "".join(chunks)

    async def _complete_async(self, prompt: str) -> str:
        """Drain ROLL's AsyncLLM request stream and return final text."""
        try:
            from vllm.utils import random_uuid

            request_id = random_uuid()
        except ImportError:  # pragma: no cover - vLLM is present in production
            request_id = str(uuid4())

        result = self.model.generate(
            prompt=prompt,
            sampling_params=self.sampling_params,
            request_id=request_id,
        )

        if inspect.isawaitable(result) and not hasattr(result, "__aiter__"):
            result = await result

        latest = None
        async for request_output in result:
            latest = request_output

        if latest is None:
            raise RuntimeError("Async vLLM returned no request output.")
        return self._extract_text(latest)

    @staticmethod
    def _extract_text(outputs: Any) -> str:
        """Extract the first completion text from vLLM output objects."""
        if isinstance(outputs, (list, tuple)):
            if not outputs:
                raise RuntimeError("vLLM returned an empty output list.")
            outputs = outputs[0]

        if isinstance(outputs, str):
            return outputs

        completions = getattr(outputs, "outputs", None)
        if completions is None and isinstance(outputs, Mapping):
            completions = outputs.get("outputs")
        if not completions:
            raise RuntimeError("vLLM output did not contain any completions.")

        completion = completions[0]
        if isinstance(completion, str):
            return completion
        if isinstance(completion, Mapping):
            text = completion.get("text")
        else:
            text = getattr(completion, "text", None)
        if text is None:
            raise RuntimeError("vLLM completion did not contain text.")
        return str(text)


class OpenAICompatibleNegotiationClient:
    """Client for a vLLM OpenAI-compatible ``/v1`` server.

    This path is intentionally independent of ``roll.third_party.vllm``.  It
    works with vLLM releases that expose the standard chat-completions API,
    including vLLM 0.28, while keeping the same ``complete`` protocol used by
    :class:`benac_p.vllm_policy.VLLMPlayerPolicy`.

    ``base_url`` may be either ``http://host:port`` or ``http://host:port/v1``;
    the client normalises it to the latter and appends
    ``/chat/completions`` for each request.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        api_key: str = "EMPTY",
        timeout: float = 300.0,
        temperature: float = 0.0,
        max_tokens: int = 512,
        enable_thinking: bool = False,
    ) -> None:
        if not base_url or not str(base_url).strip():
            raise ValueError("base_url must be non-empty.")
        if not model or not str(model).strip():
            raise ValueError("model must be non-empty.")
        if timeout <= 0:
            raise ValueError("timeout must be positive.")
        if max_tokens < 1:
            raise ValueError("max_tokens must be positive.")

        normalized_url = str(base_url).rstrip("/")
        if not normalized_url.endswith("/v1"):
            normalized_url += "/v1"
        self.base_url = normalized_url
        self.model = str(model)
        self.api_key = str(api_key)
        self.timeout = float(timeout)
        self.temperature = float(temperature)
        self.max_tokens = int(max_tokens)
        self.enable_thinking = bool(enable_thinking)

    def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        response_format: Mapping[str, Any] | None = None,
        model: str | None = None,
    ) -> str:
        """Generate one chat completion and return its text content."""

        body: dict[str, Any] = {
            "model": model or self.model,
            "messages": [
                {"role": str(message["role"]), "content": str(message["content"])}
                for message in messages
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "n": 1,
            "stream": False,
            # vLLM 0.28 uses this chat-template option for Qwen-style models.
            # Keeping reasoning disabled preserves BENAC's executable JSON
            # protocol; callers can opt in when they explicitly want it.
            "chat_template_kwargs": {"enable_thinking": self.enable_thinking},
        }
        if response_format is not None:
            body["response_format"] = dict(response_format)

        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                error_body = exc.read().decode("utf-8", errors="replace")
            except OSError:
                error_body = ""
            detail = f": {error_body}" if error_body else ""
            raise RuntimeError(
                f"OpenAI-compatible vLLM request failed with HTTP {exc.code}{detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"Could not reach OpenAI-compatible vLLM server at {self.base_url}: {exc}"
            ) from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise RuntimeError("OpenAI-compatible vLLM returned invalid JSON.") from exc

        try:
            choices = payload["choices"]
            message = choices[0]["message"]
            content = message.get("content")
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(
                "OpenAI-compatible vLLM response did not contain choices[0].message."
            ) from exc

        if isinstance(content, list):
            # Some OpenAI-compatible servers return content parts rather than a
            # single string.  BENAC only needs the textual parts.
            content = "".join(
                str(part.get("text", ""))
                for part in content
                if isinstance(part, Mapping)
            )
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError(
                "OpenAI-compatible vLLM response did not contain text content."
            )
        return content


def _run_coroutine(coroutine):
    """Run a coroutine from the benchmark's synchronous runner."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)

    # The benchmark runner is synchronous, but this fallback keeps the adapter
    # usable when called from a host application that already owns an event
    # loop.  A short-lived helper thread avoids nested asyncio.run calls.
    import threading

    result = []
    error = []

    def run():
        try:
            result.append(asyncio.run(coroutine))
        except BaseException as exc:  # pragma: no cover - host-loop fallback
            error.append(exc)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join()
    if error:
        raise error[0]
    return result[0]
