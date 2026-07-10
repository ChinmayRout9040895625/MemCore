# MemCore Deployment Walkthrough

How to run MemCore end-to-end: local Docker Compose first, then Kubernetes,
then a checklist before you point either at real traffic. Pairs with
`docs/guides/operations.md` (config reference, observability, troubleshooting)
and `deploy/k8s/README.md` (the canonical K8s manifest reference — this guide
does not repeat its detail, only walks the sequence).

## 1. Local: Docker Compose

**Prerequisites:** Docker with the `compose` plugin (`docker compose version`).
Nothing else — `docker-compose.yml` brings up all four backends (Postgres,
Qdrant, Neo4j, Redis) plus the API and worker.

```bash
cp .env.example .env
```

Edit `.env`:

- `MEMCORE_API__KEYS` — replace the dev default (`{"dev-key":"local"}`) with
  your own map, e.g. `{"my-key":"local"}`. Keep the tenant id `local` unless
  you also change other assumptions in this walkthrough.
- `MEMCORE_LLM__API_KEY` — set a real Anthropic key to enable consolidation.
  Blank falls back to Ollama/none (consolidation becomes a no-op path).

Everything else in `.env.example` (backend URLs, `MEMCORE_METRICS_PORT`) is
already correct for compose's service DNS names — leave it as-is.

```bash
docker compose up -d --build
```

First build installs the `embeddings` extra (pulls in `torch`) — expect
**~15–20 minutes** on a cold Docker cache. Subsequent builds reuse cached
layers and are fast.

Verify the API is up:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/ready
```

`/health` returns `{"status":"ok",...}` once the process is alive. `/ready`
checks every backend adapter and returns 503 `degraded` until Postgres,
Qdrant, Neo4j, and Redis are all reachable — `docker-compose.yml`'s
`depends_on: {condition: service_healthy}` on `api`/`worker` means this
should already be true once `docker compose up` reports the containers
healthy, but `/ready` is the authoritative check.

Run the SDK example against the running stack:

```bash
MEMCORE_URL=http://localhost:8000 MEMCORE_API_KEY=my-key \
    python examples/quickstart_async.py
```

(Use whatever key you put in `MEMCORE_API__KEYS`; the example defaults to
`dev-key` if `MEMCORE_API_KEY` is unset, so only omit it if you left the
`.env` default in place.)

Inspect the worker (consolidation, decay-sweep jobs):

```bash
docker compose logs -f worker
```

**Metrics.** The API serves Prometheus metrics at `http://localhost:8000/metrics`
(same published port as the app, per `docker-compose.yml`'s `api.ports`). The
worker exposes its own registry on `:9100` (`MEMCORE_METRICS_PORT=9100` in
`.env.example`), but the `worker` service in `docker-compose.yml` does not
publish any port to the host — it's reachable only from inside the compose
network (`docker compose exec worker curl localhost:9100/metrics`) unless you
add a `ports:` mapping yourself. Neither endpoint has auth; both are
non-public by convention, not by enforcement, in this local setup — the
Kubernetes ingress is what actually blocks `/metrics` from the outside (§2).

Teardown:

```bash
docker compose down       # stop containers, keep volumes (data persists)
docker compose down -v    # also drop qdrant_data/neo4j_data/redis_data/postgres_data
```

## 2. Kubernetes

**Prerequisites:**

- A cluster and `kubectl` pointed at it.
- A container registry you can push to.
- Postgres, Qdrant, Neo4j, and Redis reachable **from inside the cluster** at
  the DNS names `deploy/k8s/configmap.yaml` expects (`postgres:5432`,
  `qdrant:6333`, `neo4j:7687`, `redis:6379`) — these manifests deploy only
  the MemCore API and worker, not the backends. See `deploy/k8s/README.md`
  for the full prerequisite list.

Build and push the image, then point both deployments at it:

```bash
docker build -t myregistry.azurecr.io/memcore:latest .
docker push myregistry.azurecr.io/memcore:latest
```

Edit the `image:` field in `deploy/k8s/api-deployment.yaml` and
`deploy/k8s/worker-deployment.yaml` (both default to `memcore:latest`) to
your pushed tag.

Create the namespace and non-secret config:

```bash
kubectl apply -f deploy/k8s/namespace.yaml
kubectl apply -f deploy/k8s/configmap.yaml
```

Fill in the secret — `MEMCORE_API__KEYS`, `MEMCORE_GRAPH__PASSWORD`,
`MEMCORE_LLM__API_KEY`, and `MEMCORE_DATABASE__URL` (the DB URL lives in the
Secret, not the ConfigMap, because it embeds credentials):

```bash
cp deploy/k8s/secret.example.yaml deploy/k8s/secret.yaml
# edit deploy/k8s/secret.yaml with real values
kubectl apply -f deploy/k8s/secret.yaml
```

`deploy/k8s/secret.yaml` is gitignored — never commit your filled copy.

Apply the rest, in the order `deploy/k8s/README.md` documents:

```bash
kubectl apply -f deploy/k8s/api-deployment.yaml
kubectl apply -f deploy/k8s/worker-deployment.yaml
kubectl apply -f deploy/k8s/api-service.yaml
kubectl apply -f deploy/k8s/ingress.yaml
```

Verify the rollout:

```bash
kubectl -n memcore rollout status deploy/memcore-api
kubectl -n memcore rollout status deploy/memcore-worker
```

**Probe behavior.** `api-deployment.yaml`'s `startupProbe` (`/health`,
`failureThreshold: 30` × `periodSeconds: 10` = up to 5 minutes) exists
because the bge embedding model downloads on first use — the pod would
otherwise trip `livenessProbe` during that first-boot download. Once
`startupProbe` succeeds, `livenessProbe` (`/health`) and `readinessProbe`
(`/ready`) take over; `/ready` pulls the pod out of the Service's rotation
(without restarting it) if any backend adapter is unreachable.

Port-forward and run the example against the cluster:

```bash
kubectl -n memcore port-forward svc/memcore-api 8000:80
MEMCORE_URL=http://localhost:8000 MEMCORE_API_KEY=<key-from-secret.yaml> \
    python examples/quickstart_async.py
```

**Scraping.** `ingress.yaml` denies public access to `/ready` and `/metrics`
(`server-snippet` block). Scrape the API's `/metrics` cluster-internally —
per `deploy/k8s/README.md`, a `ServiceMonitor` or static target pointing at
`memcore-api:80`. The worker's `:9100` has no Service in front of it at
all; scrape via port-forward or a headless Service, as the README describes.

**Worker concurrency and scaling.** `worker-deployment.yaml` runs
`--concurrency=1` — required, not cosmetic: the Prometheus exposition server
on `:9100` assumes a single process binds the port, and a default prefork
worker with multiple children would race it and expose only one child's
counters (ADR-0020). Scale worker *throughput* with `replicas`
(`kubectl -n memcore scale deploy/memcore-worker --replicas=N`), not
concurrency — each replica still runs one process at `--concurrency=1`. Note
this also means decay-sweep dedupe (an in-process `asyncio.Lock`) does not
coordinate across replicas; see `docs/guides/operations.md` §6 for the known
limit. The API deployment (`replicas: 2` by default) scales normally —
`kubectl -n memcore scale deploy/memcore-api --replicas=N`.

## 3. Production checklist

- **Real API keys, never the dev default.** `MEMCORE_API__KEYS` in
  `secret.yaml` must not be the `{"dev-key":"local"}` shape from
  `.env.example`. The dev-key auto-injection only fires when
  `MEMCORE_ENV=local` *and* the map is empty; `configmap.yaml` already sets
  `MEMCORE_ENV=production`, so an empty key map there means every request
  gets `401`, not a silent dev key — but set real keys regardless.
- **Secret hygiene.** `deploy/k8s/secret.yaml` is gitignored (as is `.env`).
  Only `secret.example.yaml` (placeholder values) belongs in the repo.
- **Rate limiting is edge-only.** There is no in-app limiter — `ingress.yaml`'s
  `nginx.ingress.kubernetes.io/limit-rps: "20"` (with a 3x burst multiplier)
  is the only throttle. If your ingress controller isn't nginx, or you bypass
  the Ingress, nothing else in MemCore limits request rate.
- **TLS.** `ingress.yaml` ships without a `tls:` block — add one (e.g. via
  cert-manager annotations + a `tls:` section referencing a Secret) before
  exposing the `host:` publicly. Not included by default because certificate
  issuance is cluster/provider-specific.
- **Back up Postgres.** It's the sole source of truth (ADR-0005) — Qdrant and
  Neo4j are rebuildable projections re-indexable from the record store, so
  they don't need their own backup discipline, but Postgres does.
- **Pin image tags.** Both deployments default to `image: memcore:latest`.
  Replace with an immutable tag (or digest) per release before running in
  production — `:latest` makes rollbacks and audits ambiguous.
- **Resource sizing.** `api-deployment.yaml` and `worker-deployment.yaml`
  both start at `requests: {cpu: 250m, memory: 512Mi}` /
  `limits: {cpu: 1, memory: 1Gi}`, with `replicas: 2` (API) and `replicas: 1`
  (worker) — treat these as a floor to load-test from, not a sized-for-you
  default.
