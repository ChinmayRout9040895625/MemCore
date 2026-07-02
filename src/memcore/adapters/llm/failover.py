"""Failover :class:`LLMProvider`: primary -> fallback on provider failure.

Implements ADR-0009's Claude-Sonnet-primary / Ollama-fallback policy behind the
same port, so callers never know a failover happened (beyond the logged event
and the ``model`` recorded on the response).
"""

from __future__ import annotations

from memcore.exceptions import ProviderError
from memcore.logging import get_logger
from memcore.ports.llm_provider import LLMMessage, LLMProvider, LLMResponse

logger = get_logger("llm.failover")


class FailoverLLMProvider(LLMProvider):
    def __init__(self, primary: LLMProvider, fallback: LLMProvider) -> None:
        self._primary = primary
        self._fallback = fallback

    @property
    def model(self) -> str:
        return self._primary.model

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        json_mode: bool = False,
    ) -> LLMResponse:
        try:
            return await self._primary.complete(
                messages,
                max_tokens=max_tokens,
                temperature=temperature,
                json_mode=json_mode,
            )
        except ProviderError as exc:
            logger.warning(
                "primary LLM failed, falling back",
                extra={"primary": self._primary.model, "fallback": self._fallback.model,
                       "error": str(exc)},
            )
            return await self._fallback.complete(
                messages,
                max_tokens=max_tokens,
                temperature=temperature,
                json_mode=json_mode,
            )
