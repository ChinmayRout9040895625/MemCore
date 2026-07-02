"""LLMProvider port — used by the consolidation agent for extraction/summarize.

Primary adapter: Claude Sonnet via the Anthropic API. Fallback: local Ollama
models. A composite adapter (added in the consolidation phase) will implement
primary→fallback failover behind this same interface.

The port stays deliberately small: MemCore does not host inference, it calls out.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class LLMMessage:
    """A single chat message."""

    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass(frozen=True)
class LLMResponse:
    """A completion result plus lightweight usage accounting for cost metrics."""

    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0


class LLMProvider(ABC):
    """Port for a chat/instruction LLM."""

    @property
    @abstractmethod
    def model(self) -> str:
        """Identifier of the underlying model."""

    @abstractmethod
    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        json_mode: bool = False,
    ) -> LLMResponse:
        """Produce a completion. ``json_mode`` requests strict JSON output."""
