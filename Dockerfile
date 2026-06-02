# syntax=docker/dockerfile:1
# Production container for the auto-cxas-scrapi autonomous loop.
# Build:  docker build -t auto-cxas-scrapi .
# Run:    docker run --env-file .env auto-cxas-scrapi

# ── Stage 1: build wheel ──────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build
COPY pyproject.toml README.md ./
COPY src/ ./src/

RUN pip install --no-cache-dir build \
 && python -m build --wheel \
 && pip install --no-cache-dir dist/*.whl

# ── Stage 2: minimal runtime ─────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# Copy installed site-packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages \
                    /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy runtime entrypoint files
COPY auto_loop.py evaluate.py agent_config.py golden_tests.yaml ./
COPY tests/ ./tests/

ENV PYTHONUNBUFFERED=1 \
    AUTO_CXAS_ENV=production \
    AUTO_CXAS_LOG_LEVEL=INFO

# Non-root user for Cloud Run best practice
RUN useradd --system --no-create-home appuser
USER appuser

HEALTHCHECK NONE

CMD ["python", "auto_loop.py"]
