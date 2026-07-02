"""Anthropic :class:`LLMProvider` — Claude Sonnet, the primary consolidation
model (ADR-0009).

The SDK is imported lazily (``llm`` extra) and the client is injectable for
offline tests. ``json_mode`` is enforced via instruction + response prefilling
(the assistant turn is seeded with ``{``), the standard Anthropic pattern for
strict-JSON output.
"""

from __future__ import annotations

from typing import Any

from memcore.exceptions import ConfigurationError, ProviderError
from memcore.ports.llm_provider import LLMMessage, LLMProvider, LLMResponse


class AnthropicLLMProvider(LLMProvider):
    def __init__(
        self,
        model: str = "claude-sonnet-5",
        *,
        api_key: str | None = None,
        client: Any | None = None,
    ) -> None:
        self._model = model
        if client is None:  # pragma: no cover - requires the llm extra
            try:
                from anthropic import AsyncAnthropic
            except ImportError as exc:
                raise ConfigurationError(
                    "anthropic is not installed; install the llm extra: "
                    "pip install 'memcore[llm]'"
                ) from exc
            client = AsyncAnthropic(api_key=api_key)
        self._client = client

    @property
    def model(self) -> str:
        return self._model

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        json_mode: bool = False,
    ) -> LLMResponse:
        system_parts = [m.content for m in messages if m.role == "system"]
        chat = [
            {"role": m.role, "content": m.content}
            for m in messages
            if m.role in ("user", "assistant")
        ]
        if json_mode:
            # Prefill the assistant turn to force a JSON object response.
            chat.append({"role": "assistant", "content": "{"})
        try:
            response = await self._client.messages.create(
                model=self._model,
                system="\n\n".join(system_parts) or None,
                messages=chat,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as exc:
            raise ProviderError(f"anthropic completion failed: {exc}") from exc

        text = "".join(
            block.text for block in response.content if getattr(block, "text", None)
        )
        if json_mode:
            text = "{" + text
        usage = getattr(response, "usage", None)
        return LLMResponse(
            text=text,
            model=self._model,
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
        )
