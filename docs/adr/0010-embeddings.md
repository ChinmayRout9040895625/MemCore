# ADR-0010: Embeddings = bge-small default, pluggable providers

**Status:** Accepted (2026-07-01)

## Context
Retrieval quality and cost hinge on the embedding model. We want a strong,
free, self-hostable default with a clear upgrade path to a managed
high-accuracy model for production.

## Decision
- **Default:** `BAAI/bge-small-en-v1.5` (384-dim) via a local sentence-transformers
  adapter — free, fast, offline-capable.
- **Pluggable:** `EmbeddingProvider` port supports alternatives; **OpenAI
  `text-embedding-3-large`** is the supported production upgrade.
- Every stored vector records the `model` id that produced it, so a model change
  triggers safe, scoped re-embedding rather than silent mixed-space corruption
  (Risk R-9).
- Vector dimension is configuration, and collections are created per active
  model dimension.

## Consequences
- Mixing embedding models within one collection is prohibited; migrations
  re-embed and re-index.
- The default keeps the whole system runnable with zero external API cost;
  production can opt into higher recall at a per-call price.
