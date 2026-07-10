# MemCore Kubernetes Deployment

This directory contains Kubernetes manifests for deploying the MemCore API and worker on a Kubernetes cluster. **Backing services (Postgres, Qdrant, Neo4j, Redis) must be provisioned separately** and reachable at the DNS names configured in `configmap.yaml`.

## Prerequisites: Backing Services

Before applying these manifests, ensure the following services are deployed and accessible **within the cluster** at these DNS names:

- **Postgres** at `postgres:5432` (or update `MEMCORE_DATABASE__URL` — now in
  the Secret, see `secret.example.yaml`)
- **Qdrant** at `qdrant:6333` (or update `MEMCORE_VECTOR__URL` in ConfigMap)
- **Neo4j** at `neo4j:7687` (or update `MEMCORE_GRAPH__URL` in ConfigMap)
- **Redis** at `redis:6379` (or update `MEMCORE_REDIS__URL` in ConfigMap)

Deploy these via their official Helm charts, operators, or managed services, and ensure the `memcore` namespace can reach them. Pods will CrashLoopBackOff if these services are unavailable.

## Files Overview

- **namespace.yaml**: Creates the `memcore` namespace for resource isolation.
- **configmap.yaml**: Non-secret environment variables (backend service URLs, ports, log mode).
- **secret.example.yaml**: Template for sensitive data (API keys, passwords). Copy to `secret.yaml`, fill in real values, and keep out of version control.
- **api-deployment.yaml**: Deployment for the MemCore API with `/health` (liveness) and `/ready` (readiness) probes.
- **api-service.yaml**: ClusterIP service exposing the API on port 80 internally.
- **worker-deployment.yaml**: Deployment for the Celery worker with metrics port 9100 for Prometheus scraping.
- **ingress.yaml**: Ingress resource for external traffic with rate limiting and internal endpoint protection.

## Apply Order

Apply manifests in this order to ensure proper resource dependencies:

1. **namespace.yaml** — Creates the namespace.
2. **configmap.yaml** — Creates the ConfigMap with backend URLs and environment variables.
3. **secret.yaml** (your filled copy, not the example) — Creates secrets. Apply separately after filling in real values.
4. **api-deployment.yaml** — Deploys the API with probes.
5. **worker-deployment.yaml** — Deploys the Celery worker.
6. **api-service.yaml** — Exposes the API within the cluster.
7. **ingress.yaml** — Routes external traffic and protects internal endpoints.

## Applying the Manifests

### Apply the manifests in order (after manually preparing secret.yaml):

```bash
kubectl apply -f deploy/k8s/namespace.yaml
kubectl apply -f deploy/k8s/configmap.yaml
kubectl apply -f deploy/k8s/secret.yaml  # Your filled copy, not secret.example.yaml
kubectl apply -f deploy/k8s/api-deployment.yaml
kubectl apply -f deploy/k8s/worker-deployment.yaml
kubectl apply -f deploy/k8s/api-service.yaml
kubectl apply -f deploy/k8s/ingress.yaml
```

This sequential per-file order is the documented path — applying each
manifest explicitly avoids globbing the directory and accidentally applying
`secret.example.yaml` in place of your filled `secret.yaml`.

## Building and Pushing the Image

Before deploying, build the MemCore Docker image and push it to your container registry:

```bash
# Build the image (from the project root)
docker build -t myregistry.azurecr.io/memcore:latest .

# Push to registry
docker push myregistry.azurecr.io/memcore:latest
```

Then update the `image:` field in both **api-deployment.yaml** and **worker-deployment.yaml** to point to your registry:

```yaml
# In both deployments, replace:
image: memcore:latest   # replace with your registry tag

# With:
image: myregistry.azurecr.io/memcore:latest
```

## Cluster-Internal Endpoints

**Note on Ingress Configuration:** Recent `ingress-nginx` releases disable snippet annotations by default for security (CVE hardening). If the `/ready` and `/metrics` deny rules are silently ignored, enable snippet annotations on the controller via `allow-snippet-annotations: true`, or enforce the block via a NetworkPolicy or separate internal ingress instead.

The following endpoints are **blocked from public access** by the Ingress configuration:

- **/ready** (readiness probe) — Used only by Kubernetes for deployment health checks.
- **/metrics** (Prometheus metrics) — Exposed on the API container but blocked at the Ingress layer.

### Metrics Collection

**API Metrics:**
- **Scrape target**: `http://memcore-api.memcore.svc.cluster.local:80/metrics`
- The API Service exposes port 80 (targetPort `http` = the pod's 8000) at `/metrics`.
- Blocked at the public Ingress layer; scrape internally only.
- Configure Prometheus with a `ServiceMonitor` resource or a static scrape target pointing to `memcore-api:80`.

**Worker Metrics:**
- **Scrape target**: `http://<worker-pod-ip>:9100/metrics`
- The Celery worker exposes Prometheus metrics on port 9100 (configured via `MEMCORE_METRICS_PORT` in the ConfigMap).
- Never exposed externally; scrape via port-forward or a headless Service.

Both endpoints remain protected and are accessible only within the cluster for operational monitoring and debugging.

## Health Checks

- **Liveness Probe** (`/health`): Checks if the API container is alive. Restarts the pod if this fails.
- **Readiness Probe** (`/ready`): Checks if the API is ready to serve traffic. Removes the pod from the Service if this fails, without restarting it.

These probes ensure reliable deployments and graceful pod replacement.
