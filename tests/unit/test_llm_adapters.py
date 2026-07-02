"""LLM adapter tests with fake clients (no SDKs, no network)."""

from __future__ import annotations

import types
from typing import Any

import pytest

from memcore.adapters.inmemory import ScriptedLLMProvider
from memcore.adapters.llm import (
    AnthropicLLMProvider,
    FailoverLLMProvider,
    OllamaLLMProvider,
)
from memcore.exceptions import ProviderError
from memcore.ports.llm_provider import LLMMessage


def _msg(role: str, content: str) -> LLMMessage:
    return LLMMessage(role=role, content=content)


# -- anthropic ------------------------------------------------------------------
class _FakeAnthropicMessages:
    def __init__(self, text: str = 'ok"}', fail: bool = False) -> None:
        self.text = text
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        if self.fail:
            raise RuntimeError("overloaded")
        self.calls.append(kwargs)
        return types.SimpleNamespace(
            content=[types.SimpleNamespace(text=self.text)],
            usage=types.SimpleNamespace(input_tokens=10, output_tokens=5),
        )


def _anthropic(
    text: str = 'ok"}', fail: bool = False
) -> tuple[AnthropicLLMProvider, _FakeAnthropicMessages]:
    messages = _FakeAnthropicMessages(text=text, fail=fail)
    client = types.SimpleNamespace(messages=messages)
    return AnthropicLLMProvider("claude-sonnet-5", client=client), messages


async def test_anthropic_maps_system_and_counts_usage() -> None:
    provider, fake = _anthropic(text="hello")
    response = await provider.complete(
        [_msg("system", "be terse"), _msg("user", "hi")], max_tokens=64
    )
    assert response.text == "hello"
    assert response.input_tokens == 10 and response.output_tokens == 5
    call = fake.calls[0]
    assert call["system"] == "be terse"
    assert call["messages"] == [{"role": "user", "content": "hi"}]
    assert call["max_tokens"] == 64


async def test_anthropic_json_mode_prefills_and_restores_brace() -> None:
    provider, fake = _anthropic(text='"a": 1}')
    response = await provider.complete([_msg("user", "go")], json_mode=True)
    assert response.text == '{"a": 1}'
    # The prefill turn was sent.
    assert fake.calls[0]["messages"][-1] == {"role": "assistant", "content": "{"}


async def test_anthropic_wraps_errors() -> None:
    provider, _ = _anthropic(fail=True)
    with pytest.raises(ProviderError, match="anthropic"):
        await provider.complete([_msg("user", "hi")])


# -- ollama -----------------------------------------------------------------------
class _FakeHttpResponse:
    def __init__(self, body: dict[str, Any]) -> None:
        self._body = body

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict[str, Any]:
        return self._body


class _FakeHttpClient:
    def __init__(self, body: dict[str, Any] | None = None, fail: bool = False) -> None:
        self.body = body or {
            "message": {"content": '{"ok": true}'},
            "prompt_eval_count": 7,
            "eval_count": 3,
        }
        self.fail = fail
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def post(self, url: str, json: dict[str, Any]) -> _FakeHttpResponse:
        if self.fail:
            raise RuntimeError("connection refused")
        self.calls.append((url, json))
        return _FakeHttpResponse(self.body)


async def test_ollama_chat_payload_and_usage() -> None:
    fake = _FakeHttpClient()
    provider = OllamaLLMProvider("llama3.1", base_url="http://oll:11434/", client=fake)
    response = await provider.complete(
        [_msg("system", "sys"), _msg("user", "hi")], json_mode=True, max_tokens=99
    )
    assert response.text == '{"ok": true}'
    assert response.input_tokens == 7 and response.output_tokens == 3
    url, payload = fake.calls[0]
    assert url == "http://oll:11434/api/chat"
    assert payload["format"] == "json"
    assert payload["options"]["num_predict"] == 99
    assert payload["messages"][0] == {"role": "system", "content": "sys"}


async def test_ollama_wraps_errors() -> None:
    provider = OllamaLLMProvider(client=_FakeHttpClient(fail=True))
    with pytest.raises(ProviderError, match="ollama"):
        await provider.complete([_msg("user", "hi")])


# -- failover ---------------------------------------------------------------------
async def test_failover_uses_fallback_on_provider_error() -> None:
    primary = ScriptedLLMProvider(fail=True)
    fallback = ScriptedLLMProvider(responses=["from-fallback"])
    provider = FailoverLLMProvider(primary, fallback)
    response = await provider.complete([_msg("user", "hi")])
    assert response.text == "from-fallback"
    assert len(primary.requests) == 1 and len(fallback.requests) == 1


async def test_failover_prefers_primary_when_healthy() -> None:
    primary = ScriptedLLMProvider(responses=["from-primary"])
    fallback = ScriptedLLMProvider(responses=["from-fallback"])
    provider = FailoverLLMProvider(primary, fallback)
    response = await provider.complete([_msg("user", "hi")])
    assert response.text == "from-primary"
    assert fallback.requests == []
