"""Ollama :class:`LLMProvider` — the local fallback model (ADR-0009).

Talks to the Ollama HTTP API directly with httpx (no SDK dependency). The
client is injectable for offline tests; ``json_mode`` maps to Ollama's
``format: "json"``.
"""

from __future__ import annotations

from typing import Any

from memcore.exceptions import ConfigurationError, ProviderError
from memcore.ports.llm_provider import LLMMessage, LLMProvider, LLMResponse


class OllamaLLMProvider(LLMProvider):
    def __init__(
        self,
        model: str = "llama3.1",
        *,
        base_url: str = "http://localhost:11434",
        client: Any | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")
        if client is None:  # pragma: no cover - requires httpx at runtime
            try:
                import httpx
            except ImportError as exc:
                raise ConfigurationError(
                    "httpx is not installed; install the llm extra: "
                    "pip install 'memcore[llm]'"
                ) from exc
            client = httpx.AsyncClient(timeout=timeout_seconds)
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
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if json_mode:
            payload["format"] = "json"
        try:
            response = await self._client.post(
                f"{self._base_url}/api/chat", json=payload
            )
            response.raise_for_status()
            body = response.json()
        except Exception as exc:
            raise ProviderError(f"ollama completion failed: {exc}") from exc

        return LLMResponse(
            text=body.get("message", {}).get("content", ""),
            model=self._model,
            input_tokens=int(body.get("prompt_eval_count", 0) or 0),
            output_tokens=int(body.get("eval_count", 0) or 0),
        )
