"""Sessions + async consolidation: converse, close, consolidate, poll the job.

Closing a session enqueues consolidation (an LLM extracts durable facts in
the background). With the compose stack, set MEMCORE_LLM__API_KEY server-side
for real extraction; without it, consolidation falls back per configuration.

Run:  MEMCORE_URL=http://localhost:8000 MEMCORE_API_KEY=dev-key \
        python examples/sessions_and_consolidation.py
"""

from __future__ import annotations

import asyncio
import os

from memcore.sdk import AsyncMemCoreClient

AGENT = "session-agent"


async def main(client: AsyncMemCoreClient) -> None:
    session = await client.open_session(AGENT)
    print(f"session {session.id} opened")

    for turn in (
        "I just moved to Pune for a new job at a robotics startup.",
        "My dog Bruno is settling in well.",
    ):
        session = await client.append_message(session.id, "user", turn)
    print(f"{session.turn_count} turns buffered")

    closed = await client.close_session(session.id)
    print(f"session closed: {closed.closed} (consolidation enqueued)")

    job = await client.consolidate(session.id)
    finished = await client.wait_for_job(job.job_id, timeout=60.0)
    print(f"consolidation job {finished.job_id}: {finished.state}")

    outcome = await client.recall(AGENT, "where does the user work now?")
    for scored in outcome.results[:3]:
        print(f"  {scored.final:.3f}  {scored.memory.content}")


if __name__ == "__main__":
    async def _run() -> None:
        url = os.getenv("MEMCORE_URL", "http://localhost:8000")
        key = os.getenv("MEMCORE_API_KEY", "dev-key")
        async with AsyncMemCoreClient(url, key) as client:
            await main(client)

    asyncio.run(_run())
