# ADR-0021: Documentation — generated API reference + CI-executed examples, source-verified guides

**Status:** Accepted (2026-07-10)

## Context
By Phase 12, MemCore ships a REST API, a Python SDK, and Docker/Kubernetes
deploy artifacts — three surfaces that all change on every phase. Hand-written
documentation for any of them rots the moment the code moves: a REST field
gets renamed, an SDK method's signature changes, a deploy manifest gains a
probe, and nothing tells a docs author it happened. The project's own gate
already treats missing docs as a phase-gate failure (`CLAUDE.md`); the
question for Phase 12 is how to keep those docs correct *after* the phase
that wrote them, not just accurate on the day they were written.

## Decision

1. **The API reference is generated, not hand-written.**
   `scripts/generate_api_reference.py` reads the live FastAPI app's OpenAPI
   schema and renders `docs/api-reference.md`; a CI test regenerates the file
   and diffs it byte-for-byte against the committed copy, so any route,
   schema, or field change that isn't reflected in the doc fails CI instead
   of shipping silently stale. Endpoints that exist operationally but are
   deliberately excluded from the OpenAPI schema (health/readiness probes)
   get a hand-maintained section inside the generator itself, so they are
   still covered by the same script and the same drift test.

2. **Examples are executable scripts, not code blocks in prose.** Each script
   under `examples/` exposes a `main(client)` seam; `tests/unit/test_examples.py`
   imports and runs every one of them in CI — the three async examples against
   the in-process ASGI app, the sync twin against a mocked transport. An
   example that no longer matches the SDK's actual method names or
   signatures fails a test, not a reader.

3. **Guides remain hand-written**, because operational judgment
   (troubleshooting, config trade-offs, deployment topology reasoning) isn't
   something a schema or a script captures — but every factual claim in a
   guide (env var names, defaults, commands) is source-verified against the
   actual code/config at the time it's written or reviewed, not carried
   forward from memory of an earlier phase.

4. **Phase docs and ADRs stay the historical record**; they are not updated
   after the fact. Guides (`docs/guides/*`, `docs/sdk-quickstart.md`,
   `README.md`) are the living surface a new user or operator should read —
   they get maintained across phases, while phase docs describe what shipped
   in the phase that wrote them and are left alone afterward.

## Consequences
- Route/schema changes and SDK breaking changes fail CI's docs tests
  immediately, instead of leaving `docs/api-reference.md` or `examples/`
  silently wrong for however long until someone notices by hand.
- Guides can still drift between reviews — nothing automatically re-verifies
  a claim like "the default sweep threshold is 0.05" after it's written. This
  is an accepted gap: the generated and CI-executed layers cover the two
  highest-churn, highest-cost-of-being-wrong surfaces (wire format, working
  code samples); guides get the source-verification discipline instead of an
  automated check, which is weaker but far cheaper than a full contract test
  per prose claim.
- `scripts/generate_api_reference.py` is repo tooling under `scripts/`,
  deliberately not part of the installable `memcore` package — it depends on
  the full `api` extra and dev-only rendering logic that no runtime caller
  needs.
