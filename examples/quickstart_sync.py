"""MemCore quickstart (sync): same flow as quickstart_async, blocking client.

Run:  MEMCORE_URL=http://localhost:8000 MEMCORE_API_KEY=dev-key python examples/quickstart_sync.py
"""

from __future__ import annotations

import os

from memcore.sdk import MemCoreClient

AGENT = "quickstart-agent"


def main(client: MemCoreClient) -> None:
    record = client.remember(AGENT, "Bruno is a beagle.", tags=["pet"])
    print(f"stored memory {record.id}")
    outcome = client.recall(AGENT, "what kind of dog is bruno?")
    for scored in outcome.results:
        print(f"  {scored.final:.3f}  {scored.memory.content}")


if __name__ == "__main__":
    url = os.getenv("MEMCORE_URL", "http://localhost:8000")
    key = os.getenv("MEMCORE_API_KEY", "dev-key")
    with MemCoreClient(url, key) as client:
        main(client)
