"""Memory lifecycle: remember -> recall -> correct -> versions -> forget.

Records are immutable and versioned: a correction supersedes rather than
edits, and soft deletion is reversible server-side (POST
/v1/memories/{id}/restore — not yet wrapped by the SDK).

Run:  MEMCORE_URL=http://localhost:8000 MEMCORE_API_KEY=dev-key python examples/memory_lifecycle.py
"""

from __future__ import annotations

import asyncio
import os

from memcore.sdk import AsyncMemCoreClient, NotFoundError

AGENT = "lifecycle-agent"


async def main(client: AsyncMemCoreClient) -> None:
    original = await client.remember(
        AGENT, "Chinmay lives in Mumbai.", importance=0.7, confidence=0.6,
    )
    print(f"v1: {original.content!r} (id={original.id})")

    corrected = await client.correct_memory(
        original.id, content="Chinmay lives in Pune.", confidence=0.9,
    )
    print(f"v2: {corrected.content!r} supersedes {corrected.supersedes}")

    versions = await client.memory_versions(corrected.id)
    print(f"version chain: {[v.version for v in versions]}")

    outcome = await client.recall(AGENT, "where does chinmay live?")
    top = outcome.results[0].memory if outcome.results else None
    print(f"recall surfaces: {top.content!r}" if top else "recall found nothing")

    await client.forget_memory(corrected.id, mode="hard")
    try:
        await client.get_memory(corrected.id)
    except NotFoundError:
        print("hard-deleted memory is gone (404), as designed")


if __name__ == "__main__":
    async def _run() -> None:
        url = os.getenv("MEMCORE_URL", "http://localhost:8000")
        key = os.getenv("MEMCORE_API_KEY", "dev-key")
        async with AsyncMemCoreClient(url, key) as client:
            await main(client)

    asyncio.run(_run())
