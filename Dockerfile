# ============================================
#  🔀 RouterAI — Production Dockerfile
#  Multi-stage build + non-root user
# ============================================

# ── Build stage (install deps) ──────────────
FROM python:3.12-slim AS builder

WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Runtime stage ───────────────────────────
FROM python:3.12-slim

# Security: install only what we need
RUN apt-get update -qq \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install /usr/local

WORKDIR /app

# Create non-root user first
RUN groupadd -r routerai && useradd -r -g routerai -d /app -s /sbin/nologin routerai

# Copy source
COPY . .

# Create data directories and fix ownership
RUN mkdir -p data/cache \
    && chown -R routerai:routerai /app

# Security: run as non-root
USER routerai

EXPOSE 8900

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=15s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8900/health')" || exit 1

# Production: gunicorn + uvicorn workers
# timeout = max(stream_timeout) + buffer, default 300s
CMD ["gunicorn", \
     "--bind", "0.0.0.0:8900", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--workers", "2", \
     "--timeout", "300", \
     "--graceful-timeout", "30", \
     "--keep-alive", "5", \
     "--max-requests", "1000", \
     "--max-requests-jitter", "50", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "--pythonpath", "src", \
     "server:app"]
