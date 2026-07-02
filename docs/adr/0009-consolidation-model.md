# ADR-0009: Consolidation model = Claude Sonnet (primary), Ollama (fallback)

**Status:** Accepted (2026-07-01)

## Context
Consolidation turns raw conversation into structured memories (facts, entities,
relations) and resolves conflicts. This is the most quality-sensitive LLM use in
the system and the dominant cost driver (Risk R-3). We need strong extraction
quality with an escape hatch for cost/offline/self-host scenarios.

## Decision
- **Primary:** Claude Sonnet via the Anthropic API (`claude-sonnet-5`) as the
  default `LLMProvider`.
- **Fallback:** local **Ollama** models (default `llama3.1`), used on primary
  failure or when a deployment opts for fully local operation.
- Both sit behind `memcore.ports.llm_provider.LLMProvider`. A composite adapter
  (consolidation phase) implements primary→fallback failover transparently.
- Interaction content is treated as untrusted **data**, never instructions, to
  harden against prompt injection (Risk R-5).

## Consequences
- Two provider integrations to maintain.
- Cost/quality is tunable per deployment via configuration, not code.
- Eval suite (Phase 8) must benchmark both providers on consolidation accuracy
  and false-overwrite rate so the fallback's quality gap is quantified.
