# Multi-stage build for MemCore. Stage 1 installs the package + runtime extras
# into a venv; stage 2 is a slim runtime that copies only the venv + source.
FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy metadata first for layer caching, then source.
COPY pyproject.toml README.md ./
COPY src ./src
# Runtime extras: full default backend set + api server + observability.
RUN pip install ".[api,sql,postgres,vector,graph,working,scheduler,llm,embeddings,observability]"

FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# Non-root runtime user.
RUN useradd --create-home --uid 10001 memcore
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /build/src /app/src
WORKDIR /app
ENV PYTHONPATH=/app/src
USER memcore

EXPOSE 8000
# Default command runs the API; the worker service overrides `command`.
CMD ["uvicorn", "--factory", "memcore.api:create_app", \
     "--host", "0.0.0.0", "--port", "8000"]
