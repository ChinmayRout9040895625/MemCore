# MemCore Kubernetes Deployment

This directory contains Kubernetes manifests for deploying the full MemCore stack (API, worker, and backing services) on a Kubernetes cluster.

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

### One-liner for applying all manifests (after manually preparing secret.yaml):

```bash
kubectl apply -f deploy/k8s/namespace.yaml
kubectl apply -f deploy/k8s/configmap.yaml
kubectl apply -f deploy/k8s/secret.yaml  # Your filled copy, not secret.example.yaml
kubectl apply -f deploy/k8s/api-deployment.yaml
kubectl apply -f deploy/k8s/worker-deployment.yaml
kubectl apply -f deploy/k8s/api-service.yaml
kubectl apply -f deploy/k8s/ingress.yaml
```

Or apply non-secret resources directly:

```bash
kubectl apply -f deploy/k8s/ --exclude deploy/k8s/secret.example.yaml
```

Then separately apply your filled secret:

```bash
kubectl apply -f deploy/k8s/secret.yaml
```

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

The following endpoints are **blocked from public access** by the Ingress configuration:

- **/ready** (readiness probe) — Used only by Kubernetes for deployment health checks.
- **/metrics** (Prometheus metrics) — Exposed on the API container but blocked at the Ingress layer.

### Metrics Collection

- **API Metrics**: The API exposes Prometheus metrics on port 8000 at `/metrics`. These should be scraped via a `ServiceMonitor` or internal scrape target pointing to the `memcore-api` Service. This keeps metrics behind cluster network boundaries.

- **Worker Metrics**: The Celery worker exposes metrics on port 9100 (as configured in the ConfigMap's `MEMCORE_METRICS_PORT`). These can be scraped internally by Prometheus via a headless Service or port-forwarding. Worker metrics are never exposed externally.

Both internal endpoints remain protected and are accessible only within the cluster for operational monitoring and debugging.

## Health Checks

- **Liveness Probe** (`/health`): Checks if the API container is alive. Restarts the pod if this fails.
- **Readiness Probe** (`/ready`): Checks if the API is ready to serve traffic. Removes the pod from the Service if this fails, without restarting it.

These probes ensure reliable deployments and graceful pod replacement.
