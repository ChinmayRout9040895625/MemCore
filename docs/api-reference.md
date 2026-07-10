# MemCore API Reference

Version 0.1.0 — generated from the OpenAPI schema by `scripts/generate_api_reference.py`; do not edit by hand (a drift test regenerates and compares this file).

**Authentication:** every `/v1/*` endpoint requires the `X-API-Key` header; the key maps to a tenant (`MEMCORE_API__KEYS`). Errors are RFC-7807 `application/problem+json`.

## Endpoints

### `GET /health`

Health

| Status | Response |
|---|---|
| 200 | Successful Response — HealthResponse |

### `POST /v1/consolidate`

Consolidate

Request body: `ConsolidateRequest`

| Status | Response |
|---|---|
| 202 | Successful Response — JobResponse |
| 422 | Validation Error — HTTPValidationError |

### `POST /v1/decay`

Run Decay

Enqueue a decay sweep for the calling tenant (snapshot + prune).

| Status | Response |
|---|---|
| 202 | Successful Response — JobResponse |

### `GET /v1/jobs/{job_id}`

Job Status

| Parameter | In | Type | Required |
|---|---|---|---|
| `job_id` | path | string | yes |

| Status | Response |
|---|---|
| 200 | Successful Response — JobResponse |
| 422 | Validation Error — HTTPValidationError |

### `POST /v1/memories`

Remember

Request body: `RememberRequest`

| Status | Response |
|---|---|
| 201 | Successful Response — MemoryResponse |
| 422 | Validation Error — HTTPValidationError |

### `GET /v1/memories/{memory_id}`

Get Memory

| Parameter | In | Type | Required |
|---|---|---|---|
| `memory_id` | path | string | yes |

| Status | Response |
|---|---|
| 200 | Successful Response — MemoryResponse |
| 422 | Validation Error — HTTPValidationError |

### `PATCH /v1/memories/{memory_id}`

Correct Memory

| Parameter | In | Type | Required |
|---|---|---|---|
| `memory_id` | path | string | yes |

Request body: `CorrectMemoryRequest`

| Status | Response |
|---|---|
| 200 | Successful Response — MemoryResponse |
| 422 | Validation Error — HTTPValidationError |

### `DELETE /v1/memories/{memory_id}`

Forget Memory

| Parameter | In | Type | Required |
|---|---|---|---|
| `memory_id` | path | string | yes |
| `mode` | query | string | no |

| Status | Response |
|---|---|
| 204 | Successful Response |
| 422 | Validation Error — HTTPValidationError |

### `POST /v1/memories/{memory_id}/restore`

Restore Memory

| Parameter | In | Type | Required |
|---|---|---|---|
| `memory_id` | path | string | yes |

| Status | Response |
|---|---|
| 200 | Successful Response — MemoryResponse |
| 422 | Validation Error — HTTPValidationError |

### `GET /v1/memories/{memory_id}/versions`

Get Versions

| Parameter | In | Type | Required |
|---|---|---|---|
| `memory_id` | path | string | yes |

| Status | Response |
|---|---|
| 200 | Successful Response — VersionsResponse |
| 422 | Validation Error — HTTPValidationError |

### `POST /v1/recall`

Recall

Request body: `RecallRequest`

| Status | Response |
|---|---|
| 200 | Successful Response — RecallResponse |
| 422 | Validation Error — HTTPValidationError |

### `POST /v1/sessions`

Open Session

Request body: `OpenSessionRequest`

| Status | Response |
|---|---|
| 201 | Successful Response — SessionResponse |
| 422 | Validation Error — HTTPValidationError |

### `GET /v1/sessions/{session_id}`

Get Session

| Parameter | In | Type | Required |
|---|---|---|---|
| `session_id` | path | string | yes |

| Status | Response |
|---|---|
| 200 | Successful Response — SessionResponse |
| 422 | Validation Error — HTTPValidationError |

### `POST /v1/sessions/{session_id}/close`

Close Session

| Parameter | In | Type | Required |
|---|---|---|---|
| `session_id` | path | string | yes |

| Status | Response |
|---|---|
| 200 | Successful Response — SessionResponse |
| 422 | Validation Error — HTTPValidationError |

### `POST /v1/sessions/{session_id}/messages`

Append Message

| Parameter | In | Type | Required |
|---|---|---|---|
| `session_id` | path | string | yes |

Request body: `AppendMessageRequest`

| Status | Response |
|---|---|
| 202 | Successful Response — SessionResponse |
| 422 | Validation Error — HTTPValidationError |

## Operational endpoints (not in the OpenAPI schema)

These are deliberately excluded from the schema (`include_in_schema=False`)
because they are for probes and scrapers, not API clients:

| Method & path | Purpose |
|---|---|
| `GET /ready` | Readiness probe: pings each backing store (duck-typed adapter `ping()`); returns 200 `{"status": "ready"}` or 503 `{"status": "degraded"}` with per-component detail. No auth. |
| `GET /metrics` | Prometheus exposition for the API process; 501 problem+json with an install hint when the `observability` extra is absent. No auth — keep it cluster-internal (the shipped ingress blocks it). |

## Models

### `HealthResponse`

| Field | Type | Required | Default |
|---|---|---|---|
| `status` | string | yes | `—` |
| `version` | string | yes | `—` |

### `ConsolidateRequest`

| Field | Type | Required | Default |
|---|---|---|---|
| `session_id` | string | yes | `—` |

### `JobResponse`

| Field | Type | Required | Default |
|---|---|---|---|
| `job_id` | string | yes | `—` |
| `state` | string | yes | `—` |

### `HTTPValidationError`

| Field | Type | Required | Default |
|---|---|---|---|
| `detail` | array[ValidationError] | no | `—` |

### `RememberRequest`

| Field | Type | Required | Default |
|---|---|---|---|
| `agent_id` | string | yes | `—` |
| `content` | string | yes | `—` |
| `type` | MemoryType | no | `semantic` |
| `importance` | number | no | `0.5` |
| `confidence` | number | no | `1.0` |
| `tags` | array[string] | no | `—` |

### `MemoryResponse`

| Field | Type | Required | Default |
|---|---|---|---|
| `memory` | MemoryRecord | yes | `—` |

### `CorrectMemoryRequest`

| Field | Type | Required | Default |
|---|---|---|---|
| `content` | string \| null | no | `—` |
| `importance` | number \| null | no | `—` |
| `confidence` | number \| null | no | `—` |
| `tags` | array[string] \| null | no | `—` |

### `VersionsResponse`

| Field | Type | Required | Default |
|---|---|---|---|
| `versions` | array[MemoryRecord] | yes | `—` |

### `RecallRequest`

| Field | Type | Required | Default |
|---|---|---|---|
| `agent_id` | string | yes | `—` |
| `query` | string | yes | `—` |
| `k` | integer | no | `8` |
| `types` | array[MemoryType] \| null | no | `—` |
| `weights` | RecallWeights \| null | no | `—` |
| `graph_expand` | boolean \| null | no | `—` |
| `rerank` | boolean | no | `False` |
| `as_context` | boolean | no | `False` |

### `RecallResponse`

| Field | Type | Required | Default |
|---|---|---|---|
| `results` | array[ScoredMemory] | yes | `—` |
| `context` | string \| null | no | `—` |
| `context_tokens` | integer \| null | no | `—` |

### `OpenSessionRequest`

| Field | Type | Required | Default |
|---|---|---|---|
| `agent_id` | string | yes | `—` |

### `SessionResponse`

| Field | Type | Required | Default |
|---|---|---|---|
| `session` | Session | yes | `—` |

### `AppendMessageRequest`

| Field | Type | Required | Default |
|---|---|---|---|
| `role` | string | yes | `—` |
| `content` | string | yes | `—` |
| `metadata` | object | no | `—` |

### `ValidationError`

| Field | Type | Required | Default |
|---|---|---|---|
| `loc` | array[string \| integer] | yes | `—` |
| `msg` | string | yes | `—` |
| `type` | string | yes | `—` |
| `input` | any | no | `—` |
| `ctx` | object | no | `—` |

### `MemoryType`

The three cognitive memory tiers (see docs/design/taxonomy.md).

Enum (string): `working`, `episodic`, `semantic`

### `MemoryRecord`

A single versioned unit of memory (working, episodic or semantic).

``embedding_ref`` is the id of the vector in the vector store (if any);
the vector itself is not carried on the model to keep it lightweight.

| Field | Type | Required | Default |
|---|---|---|---|
| `id` | string | no | `—` |
| `tenant_id` | string | yes | `—` |
| `agent_id` | string | yes | `—` |
| `type` | MemoryType | yes | `—` |
| `content` | string | yes | `—` |
| `embedding_ref` | string \| null | no | `—` |
| `importance` | number | no | `0.5` |
| `confidence` | number | no | `1.0` |
| `created_at` | string | no | `—` |
| `last_accessed_at` | string \| null | no | `—` |
| `access_count` | integer | no | `0` |
| `decay_score` | number | no | `1.0` |
| `valid_from` | string | no | `—` |
| `valid_to` | string \| null | no | `—` |
| `version` | integer | no | `1` |
| `supersedes` | string \| null | no | `—` |
| `status` | MemoryStatus | no | `active` |
| `source_refs` | array[string] | no | `—` |
| `tags` | array[string] | no | `—` |
| `metadata` | object | no | `—` |

### `RecallWeights`

Exponent weights: 0 neutralizes a factor, >1 sharpens it.

| Field | Type | Required | Default |
|---|---|---|---|
| `relevance` | number | no | `1.0` |
| `recency` | number | no | `1.0` |
| `importance` | number | no | `1.0` |

### `ScoredMemory`

A memory returned from retrieval with its hybrid-score breakdown.

``final`` is the blended score; the components are exposed so callers can
audit *why* a memory ranked where it did (a first-class product feature).

| Field | Type | Required | Default |
|---|---|---|---|
| `memory` | MemoryRecord | yes | `—` |
| `relevance` | number | yes | `—` |
| `recency` | number | yes | `—` |
| `importance` | number | yes | `—` |
| `final` | number | yes | `—` |

### `Session`

A session groups interactions and tracks consolidation progress.

| Field | Type | Required | Default |
|---|---|---|---|
| `id` | string | no | `—` |
| `tenant_id` | string | yes | `—` |
| `agent_id` | string | yes | `—` |
| `opened_at` | string | no | `—` |
| `last_activity` | string | no | `—` |
| `token_count` | integer | no | `0` |
| `turn_count` | integer | no | `0` |
| `consolidation_watermark` | string \| null | no | `—` |
| `closed` | boolean | no | `False` |
| `metadata` | object | no | `—` |

### `MemoryStatus`

Lifecycle status of a memory record.

Records are immutable and versioned (ADR-007): an UPDATE writes a new
version and marks the prior one ``SUPERSEDED``. Forgetting is reversible
(``SOFT_DELETED``) until a retention/GDPR job makes it ``HARD_DELETED``.

Enum (string): `active`, `superseded`, `soft_deleted`, `hard_deleted`
