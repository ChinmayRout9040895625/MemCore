# ADR-0013: Hybrid retrieval engine design

**Status:** Accepted (2026-07-02)

## Context
Cosine-only retrieval fails MemCore's product promise: stale-but-similar
memories outrank fresh relevant ones, exact identifiers lose to fuzzy semantic
neighbours, and structurally-related facts ("Alice's manager") never surface.
The hot path must stay LLM-free (ADR-0001) and inside the latency budget.

## Decision

**Scoring.** `relevance = (1-α)·vector + α·lexical_overlap` (α default 0.3),
then `final = relevance^wr · recency^wt · importance^wi` with caller-supplied
exponent weights (default 1.0 each; 0 neutralizes a factor, >1 sharpens it).
Multiplicative blending suppresses candidates weak in any heavily-weighted
factor. Recency is `exp(-age/τ)` with per-type τ (working 6h, episodic 7d,
semantic 30d — configurable).

**Graph expansion.** Query tokens → entity lookup (aliases included) → bounded
neighbourhood walk (hops ≤ 2, capped entity/relation counts) → the relations'
**provenance memory ids** join the candidate set with a relevance floor
(default 0.45), because structural relatedness carries signal wording doesn't.
Consolidation (Phase 5) populates provenance. Cross-agent provenance is
filtered out at scoring time; latency is protected by the hop/limit caps.

**Rerank.** Optional and budget-gated (`rerank=true`): v1 re-sorts the top
window (20) lexically. This is an explicit placeholder slot — a cross-encoder
or LLM reranker replaces the sort without any API change.

**Reinforcement.** Every recalled memory gets `access_count`/`last_accessed_at`
bumped, feeding importance and decay (Phase 6/7): retrieval strengthens memory.

**Embeddings.** bge-small via sentence-transformers (lazy import; heavy deps in
the `embeddings` extra; encode runs in a worker thread) and OpenAI
`text-embedding-3-large` (injectable client). Query embeddings are LRU-cached
per model.

**Context assembly.** `as_context=true` returns a deduped, provenance-annotated
block packed to a token budget (chars/4 heuristic until real tokenization).

## Consequences
- All knobs live in `RetrievalSettings`; the eval suite (Phase 8) tunes them
  against benchmarks instead of folklore.
- Graph expansion cost is bounded and skippable per request (`graph_expand`).
- The lexical component uses simple token overlap, not BM25 with corpus
  statistics — revisit if eval shows exact-term recall gaps.
