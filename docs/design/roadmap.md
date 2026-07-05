# Implementation Roadmap

Built phase-by-phase. Each phase: design → implementation → tests → docs →
self-review → fix → approval gate. Never skip tests, docs, or ADR updates.

| Phase | Scope | Status |
|-------|-------|--------|
| 1 | Project setup & repository structure | ✅ Complete |
| 2 | Storage layer — Qdrant, Neo4j, Redis adapters | ✅ Complete |
| 3 | Memory APIs (FastAPI: sessions, memories, recall) | ✅ Complete |
| 4 | Retrieval engine (hybrid scoring, graph expansion) | ✅ Complete |
| 5 | Consolidation agent (extract, conflict-resolve, ops) | ✅ Complete |
| 6 | Importance scoring | ✅ Complete |
| 7 | Memory decay & pruning | ✅ Complete |
| 8 | Evaluation framework & baselines | ✅ Complete |
| 9 | Python SDK | ✅ Complete |
| 10 | Observability & monitoring | ⏳ Next |
| 11 | Deployment (Docker, K8s, CI/CD) | Planned |
| 12 | Documentation & examples | Planned |

See per-phase records under `docs/design/phase-*.md`.
