"""MemCore quickstart (async): store a memory, recall it by meaning.

Run against a live MemCore (e.g. the docker-compose stack):
    MEMCORE_URL=http://localhost:8000 MEMCORE_API_KEY=dev-key \
        python examples/quickstart_async.py
"""

from __future__ import annotations

import asyncio
import os

from memcore.sdk import AsyncMemCoreClient

AGENT = "quickstart-agent"


async def main(client: AsyncMemCoreClient) -> None:
    record = await client.remember(
        AGENT, "Chinmay prefers dark mode in every editor.",
        importance=0.8, tags=["preference"],
    )
    print(f"stored memory {record.id} (importance={record.importance})")

    outcome = await client.recall(AGENT, "what UI theme does the user like?")
    for scored in outcome.results:
        print(f"  {scored.final:.3f}  {scored.memory.content}")


if __name__ == "__main__":
    async def _run() -> None:
        url = os.getenv("MEMCORE_URL", "http://localhost:8000")
        key = os.getenv("MEMCORE_API_KEY", "dev-key")
        async with AsyncMemCoreClient(url, key) as client:
            await main(client)

    asyncio.run(_run())
