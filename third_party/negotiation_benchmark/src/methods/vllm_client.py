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
from dataclasses import dataclass
from typing import Any, Mapping, Sequence
from uuid import uuid4


@dataclass(frozen=True)
class VLLMToolCall:
    """One parsed OpenAI-compatible function/tool call."""

    name: str
    arguments: Mapping[str, Any] | None
    tool_call_id: str = ""
    raw_arguments: Any = None


@dataclass(frozen=True)
class VLLMChatCompletion:
    """The part of a chat completion needed by BENAC's native tool protocol."""

    content: str
    tool_calls: tuple[VLLMToolCall, ...]
    raw_message: Mapping[str, Any]
    usage: Mapping[str, Any]


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
    including vLLM 0.28.  ``complete_with_tools`` is the native BENAC
    interface: it sends OpenAI ``tools`` with ``tool_choice=auto`` and
    returns parsed tool calls without translating a missing call into an
    action.

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

    def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        response_format: Mapping[str, Any] | None = None,
        model: str | None = None,
    ) -> str:
        """Generate a legacy text completion and return its content.

        This method remains for the older text-client protocol.  BENAC's
        native tool policy uses :meth:`complete_with_tools` instead.
        """

        completion = self._request(
            messages,
            response_format=response_format,
            model=model,
        )
        return completion.content

    def complete_with_tools(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        tools: Sequence[Mapping[str, Any]],
        tool_choice: str | Mapping[str, Any] = "auto",
        parallel_tool_calls: bool = False,
        model: str | None = None,
    ) -> VLLMChatCompletion:
        """Generate a native tool-calling completion.

        The server receives ``tools``, ``tool_choice=auto`` and
        ``parallel_tool_calls=false``.  A response with no tool calls is
        returned as an empty ``tool_calls`` tuple for the policy layer to
        classify and retry; it is never silently converted into ``PASS``.
        """

        if not tools:
            raise ValueError("At least one tool is required for native tool calling.")
        return self._request(
            messages,
            model=model,
            tools=tools,
            tool_choice=tool_choice,
            parallel_tool_calls=parallel_tool_calls,
        )

    def _request(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        response_format: Mapping[str, Any] | None = None,
        model: str | None = None,
        tools: Sequence[Mapping[str, Any]] | None = None,
        tool_choice: str | Mapping[str, Any] | None = None,
        parallel_tool_calls: bool | None = None,
    ) -> VLLMChatCompletion:
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
        }
        if response_format is not None:
            body["response_format"] = dict(response_format)
        if tools is not None:
            body["tools"] = [dict(tool) for tool in tools]
            body["tool_choice"] = tool_choice or "auto"
            body["parallel_tool_calls"] = (
                False if parallel_tool_calls is None else bool(parallel_tool_calls)
            )

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
            if not isinstance(message, Mapping):
                raise TypeError("message must be an object")
            content = self._extract_content(message.get("content"))
            raw_tool_calls = message.get("tool_calls") or ()
            if not isinstance(raw_tool_calls, (list, tuple)):
                raise TypeError("tool_calls must be a list")
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(
                "OpenAI-compatible vLLM response did not contain choices[0].message."
            ) from exc

        tool_calls = tuple(self._parse_tool_call(raw_call) for raw_call in raw_tool_calls)
        usage = payload.get("usage")
        return VLLMChatCompletion(
            content=content,
            tool_calls=tool_calls,
            raw_message=dict(message),
            usage=dict(usage) if isinstance(usage, Mapping) else {},
        )

    @staticmethod
    def _extract_content(content: Any) -> str:
        """Normalise OpenAI string or content-part responses to text."""

        if content is None:
            return ""
        if isinstance(content, list):
            return "".join(
                str(part.get("text", ""))
                for part in content
                if isinstance(part, Mapping)
            )
        return str(content)

    @staticmethod
    def _parse_tool_call(raw_call: Any) -> VLLMToolCall:
        """Parse a server tool call while preserving malformed arguments."""

        if not isinstance(raw_call, Mapping):
            return VLLMToolCall(name="", arguments=None, raw_arguments=raw_call)
        function = raw_call.get("function")
        if not isinstance(function, Mapping):
            return VLLMToolCall(
                name="",
                arguments=None,
                tool_call_id=str(raw_call.get("id", "")),
                raw_arguments=None,
            )

        raw_arguments = function.get("arguments")
        arguments: Mapping[str, Any] | None = None
        if isinstance(raw_arguments, Mapping):
            arguments = dict(raw_arguments)
        elif isinstance(raw_arguments, str):
            try:
                decoded = json.loads(raw_arguments)
            except json.JSONDecodeError:
                decoded = None
            if isinstance(decoded, Mapping):
                arguments = dict(decoded)
        return VLLMToolCall(
            name=str(function.get("name", "")),
            arguments=arguments,
            tool_call_id=str(raw_call.get("id", "")),
            raw_arguments=raw_arguments,
        )


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
