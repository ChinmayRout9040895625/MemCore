"""Scripted :class:`LLMProvider` for tests and offline development.

Returns queued responses in order (repeating the last one when exhausted) and
records every request for assertions.
"""

from __future__ import annotations

from memcore.exceptions import ProviderError
from memcore.ports.llm_provider import LLMMessage, LLMProvider, LLMResponse


class ScriptedLLMProvider(LLMProvider):
    def __init__(self, responses: list[str] | None = None, *, fail: bool = False) -> None:
        self._responses = list(responses or [])
        self._fail = fail
        self.requests: list[list[LLMMessage]] = []

    @property
    def model(self) -> str:
        return "scripted"

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        json_mode: bool = False,
    ) -> LLMResponse:
        self.requests.append(list(messages))
        if self._fail:
            raise ProviderError("scripted failure")
        if not self._responses:
            raise ProviderError("scripted provider has no responses queued")
        text = (
            self._responses.pop(0) if len(self._responses) > 1 else self._responses[0]
        )
        return LLMResponse(text=text, model="scripted")
