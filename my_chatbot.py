"""A minimal real chatbot with memory, built on top of MemCore.

This is a genuine application -- not a test script. It:
  1. Recalls relevant memories before replying (so the AI "knows" past facts).
  2. Asks a local Ollama model to generate a real conversational reply.
  3. Logs the conversation into a MemCore session.
  4. On exit, closes the session -- MemCore's own AI pipeline automatically
     extracts new facts from the conversation and stores them.

Run it, chat for a bit, type 'bye'. Run it again later: it remembers you,
because the memories live in the still-running MemCore server, independent
of this script.

Usage:
    python my_chatbot.py
"""

from __future__ import annotations

import httpx

from memcore.sdk import MemCoreClient

MEMCORE_URL = "http://localhost:8000"  # the real Docker stack (persists!)
API_KEY = "dev-key"
AGENT_ID = "my-chat-buddy"  # change this to give the bot a separate "memory"

OLLAMA_URL = "http://localhost:11434"
MODEL = "llama3.2:3b"


def ask_ollama(prompt: str) -> str:
    """Ask the local model to generate a conversational reply."""
    response = httpx.post(
        f"{OLLAMA_URL}/api/generate",
        json={"model": MODEL, "prompt": prompt, "stream": False},
        timeout=120,
    )
    response.raise_for_status()
    return str(response.json()["response"]).strip()


def main() -> None:
    # timeout=180: closing a session runs real AI extraction (Ollama), which
    # can take 30-60s on CPU -- the SDK's 10s default is too short for that.
    client = MemCoreClient(MEMCORE_URL, API_KEY, timeout=180.0)
    session = client.open_session(AGENT_ID)

    print("Chat with your memory-enabled bot. Type 'bye' to end.\n")

    while True:
        user_input = input("You: ").strip()
        if not user_input:
            continue
        if user_input.lower() in ("bye", "exit", "quit"):
            break

        # 1. Recall anything MemCore already knows that's relevant.
        outcome = client.recall(AGENT_ID, user_input, k=3)
        memory_lines = [f"- {r.memory.content}" for r in outcome.results]
        memory_context = "\n".join(memory_lines) if memory_lines else "(nothing yet)"

        # 2. Generate a real reply, grounded in those memories.
        prompt = (
            "You are a friendly, concise assistant. Here is what you "
            f"remember about this user:\n{memory_context}\n\n"
            f"The user just said: \"{user_input}\"\n"
            "Reply naturally in 1-2 sentences. Use the memories only if relevant."
        )
        reply = ask_ollama(prompt)
        print(f"Bot: {reply}\n")

        # 3. Log both turns so MemCore can learn from them later.
        client.append_message(session.id, "user", user_input)
        client.append_message(session.id, "assistant", reply)

    # 4. Closing the session triggers automatic fact extraction in the
    #    background -- but close_session() returns the instant the job is
    #    QUEUED, not when it finishes. Explicitly consolidate + wait for the
    #    job so "Done" is actually true. (Consolidation is idempotent per
    #    session watermark, so this second trigger is a safe, cheap no-op
    #    if the auto-triggered one already finished first.)
    print("\nSaving what I learned from this conversation "
          "(can take a couple minutes on a cold local model)...")
    client.close_session(session.id)
    job = client.consolidate(session.id)
    finished = client.wait_for_job(job.job_id, timeout=300.0)
    print(f"Done ({finished.state}). Run this script again -- I'll remember.")
    client.close()


if __name__ == "__main__":
    main()
