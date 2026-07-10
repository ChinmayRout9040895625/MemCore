# MemCore Python SDK — Quickstart

## Install

```bash
pip install 'memcore[sdk]'   # pydantic, pydantic-settings + httpx only; no server dependencies
# Not on PyPI yet — until published, install from a checkout: pip install -e '.[sdk]'
```

## Async

```python
import asyncio
from memcore.sdk import AsyncMemCoreClient


async def main() -> None:
    async with AsyncMemCoreClient("http://localhost:8000", "your-api-key") as client:
        # Store a memory (importance/confidence optional, 0..1).
        record = await client.remember(
            "agent-1", "Chinmay prefers dark mode.", importance=0.8, tags=["pref"]
        )

        # Hybrid recall (relevance x recency x reinforced importance).
        outcome = await client.recall("agent-1", "what UI theme does chinmay like?")
        for scored in outcome.results:
            print(f"{scored.final:.3f}  {scored.memory.content}")

        # Sessions + async consolidation.
        session = await client.open_session("agent-1")
        await client.append_message(session.id, "user", "I moved to Pune last week.")
        await client.close_session(session.id)  # enqueues consolidation

        # Trigger a decay sweep and wait for it.
        job = await client.run_decay()
        job = await client.wait_for_job(job.job_id)
        print(job.state)  # a failed job returns "failed"; it does not raise


asyncio.run(main())
```

## Sync

```python
from memcore.sdk import MemCoreClient

with MemCoreClient("http://localhost:8000", "your-api-key") as client:
    record = client.remember("agent-1", "Bruno is a beagle.")
    print(client.get_memory(record.id).content)
```

## Errors and retries

Every failure is a `memcore.sdk.MemCoreClientError`:

- `AuthError` (401), `NotFoundError` (404), `ConflictError` (409),
  `ValidationAPIError` (422), `ServerError` (5xx) — typed from the server's
  problem+json body (`.status`, `.title`, `.detail`).
- `TransportError` — network failure after retries.
- `JobTimeout` — `wait_for_job` exceeded its timeout.

GET requests are retried automatically on 429/502/503/504 and network errors
(exponential backoff, 3 attempts by default — tune with
`RetryPolicy(max_attempts=..., backoff_base=..., backoff_cap=...)` from
`memcore.sdk`). Writes (POST/PATCH/DELETE) are never retried
automatically: an ambiguous failure could otherwise duplicate a write.
A retried 429 that still fails after all attempts surfaces as a plain
`APIError` — there is no dedicated `RateLimitError` class yet.

Note: `memcore.sdk.NotFoundError`/`ConflictError` are distinct classes from
the server-side `memcore.exceptions` classes of the same names.
