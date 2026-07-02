"""LLM provider adapters (ADR-0009).

Primary: Claude Sonnet via the Anthropic API. Fallback: local Ollama.
``FailoverLLMProvider`` composes them transparently behind the port.
"""

from memcore.adapters.llm.anthropic import AnthropicLLMProvider
from memcore.adapters.llm.failover import FailoverLLMProvider
from memcore.adapters.llm.ollama import OllamaLLMProvider

__all__ = ["AnthropicLLMProvider", "FailoverLLMProvider", "OllamaLLMProvider"]
