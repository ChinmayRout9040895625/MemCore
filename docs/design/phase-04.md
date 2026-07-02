# Phase 4 — Retrieval Engine

## Objective
Replace recall v1 with the full hybrid retrieval engine: real embeddings,
caller-tunable weights, lexical hybrid, bounded graph expansion, optional
rerank, and prompt-ready context assembly. Design recorded in ADR-0013.

## Delivered

**Embedding adapters** (`adapters/embeddings/`)
- `BgeEmbeddingProvider` — bge-small via sentence-transformers; lazy import
  (heavy deps live in the `embeddings` extra), normalized vectors, encode in a
  worker thread; dimension self-declared from the model.
- `OpenAIEmbeddingProvider` — `text-embedding-3-large`/`-small`; injectable
  client (unit-testable offline), order restored via the API's `index`,
  errors wrapped in `ProviderError`; unknown models require an explicit
  dimension.
- Factory wires both; `settings.embedding.api_key` added.

**Retrieval engine** (`services/recall.py`)
- `relevance = (1-α)·vector + α·lexical` and
  `final = relevance^wr · recency^wt · importance^wi` (`ScoreWeights`).
- Graph expansion: query tokens → entities (incl. aliases) → hop/limit-bounded
  neighbourhood → provenance memory ids as candidates with a relevance floor;
  cross-agent provenance filtered; disable per request with
  `graph_expand=false`.
- Budget-gated lexical rerank of the top window (placeholder slot for a
  cross-encoder/LLM reranker).
- Query-embedding LRU cache (per model, 1024 entries).
- All knobs in `RetrievalSettings` (`MEMCORE_RETRIEVAL__*`).

**Context assembly** (`services/context.py`) — dedupe, provenance annotation,
token-budget packing; exposed via `as_context=true` on `/v1/recall`, which now
also accepts `weights`, `graph_expand`, and `rerank`.

**Wiring** — `GraphStore` joins `AppState`/`build_state`; recall gets graph +
retrieval settings.

## Tests
Scoring primitives (overlap, blend clamps); zero-weight neutralization flipping
rankings both ways; graph expansion surfacing a lexically-unrelated memory via
provenance (and staying hidden when disabled); cross-agent graph isolation;
rerank preferring exact identifier matches; embed-cache hit counting; context
dedupe/budget/empty cases; bge via a faked sentence-transformers module; OpenAI
via a fake client (ordering, error wrapping, unknown-model handling); API-level
weights + context test.

## Notes
- torch/sentence-transformers resolve on Python 3.14 (torch 2.12.1) but are
  ~2.5 GB; CI and unit tests use fakes — the real model path is exercised by
  the eval suite (Phase 8) where retrieval quality is actually measured.
- Lexical component is token overlap, not corpus-statistics BM25 (ADR-0013
  flags the revisit condition).

## Self-review
Issues found and fixed before sign-off are listed in the delivery message.
