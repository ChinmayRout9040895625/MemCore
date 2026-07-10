# MemCore examples

Runnable end-to-end scripts against any MemCore server. Each is also executed
in CI against an in-process app (`tests/unit/test_examples.py`), so they are
guaranteed current.

## Setup

```bash
pip install 'memcore[sdk]'  # not on PyPI yet — from a checkout use: pip install -e '.[sdk]'
# Bring up a local stack (from the repo root):
cp .env.example .env && docker compose up -d --build
```

Defaults target the compose stack: `MEMCORE_URL=http://localhost:8000`,
`MEMCORE_API_KEY=dev-key` (the dev key maps to the `local` tenant when no
keys are configured; set `MEMCORE_API__KEYS` in `.env` for real keys).

## Scripts

| Script | Shows |
|---|---|
| `quickstart_async.py` | remember + hybrid recall (async client) |
| `quickstart_sync.py` | the same flow with the blocking client |
| `memory_lifecycle.py` | versioned correction, version chain, hard delete |
| `sessions_and_consolidation.py` | sessions, async consolidation job, recall of extracted facts |

Run any of them:

```bash
python examples/quickstart_async.py
```
