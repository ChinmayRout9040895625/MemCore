# Memory Taxonomy

MemCore models three cognitive memory tiers.

| Dimension | Working | Episodic | Semantic |
|-----------|---------|----------|----------|
| Scope | Session | Agent timeline | Agent knowledge base |
| Lifespan | Minutes–hours (TTL) | Long, decays | Longest, reinforced |
| Store | Redis | Vector + Postgres + archive | Vector + Graph + Postgres |
| Unit | Turn / scratch KV | Event | Fact / Entity / Relation |
| Written by | Ingest (sync) | Consolidation (async) | Consolidation (async) |
| Retrieval | Direct / recent-N | Time + semantic | Semantic + graph expansion |
| Mutable? | Ephemeral | Append-only | Versioned / superseded |

## Lifecycle

```
raw interaction
  → working buffer
    → (consolidation) → episodic event(s) + candidate facts
      → dedup / entity-link / conflict-resolve
        → semantic memory (versioned, provenanced)
```

Episodic memories can be **abstracted** into semantic generalizations; semantic
memories are **reinforced** by repeated retrieval or restatement, which raises
importance and slows decay.

## Modeled in code (Phase 1)

- `MemoryType` — working | episodic | semantic
- `MemoryRecord` — the versioned unit, with bitemporal validity
  (`valid_from`/`valid_to` = world-time; `created_at`/`version` = knowledge-time)
- `Entity`, `Relation` — knowledge-graph primitives
- `Interaction` — the raw archived turn
