# Multi-stage Dockerfile for Alpaca NautilusTrader instance
# Optimized for strict VPS memory constraints (180MB RAM hard limit)

# ==============================================================================
# Stage 1: Build stage (compile / build dependencies in isolated builder)
# ==============================================================================
FROM python:3.12-slim-bookworm AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    git \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Upgrade build tools
RUN pip install --no-cache-dir --upgrade pip setuptools wheel hatchling

# Copy project definition and source for dependency resolution
COPY pyproject.toml README.md /build/
COPY nautilus_trader /build/nautilus_trader

# Install project dependencies into virtual environment
RUN pip install --no-cache-dir .

# ==============================================================================
# Stage 2: Runtime stage (minimal lean image to minimize RAM & disk footprint)
# ==============================================================================
FROM python:3.12-slim-bookworm AS runtime

LABEL maintainer="Alpaca NautilusTrader Team"
LABEL description="Alpaca NautilusTrader Paper/Live Trading Container with 180MB Memory Guard"

# System packages: ca-certificates for TLS, curl for health checks, procps for process diagnostics
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    procps \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Memory & Runtime Optimization Flags:
# - MALLOC_ARENA_MAX=2: Constrains glibc memory allocation arenas to prevent multi-threaded memory bloat
# - PYTHONUNBUFFERED=1: Flushes stdout/stderr immediately for real-time logging
# - PYTHONDONTWRITEBYTECODE=1: Avoids writing .pyc bytecode to disk / overlayfs
# - PIP_NO_CACHE_DIR=1: Disables pip caching
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MALLOC_ARENA_MAX=2 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/app"

# Copy virtual environment from builder stage
COPY --from=builder /opt/venv /opt/venv

# Create non-root application user for least privilege execution
RUN groupadd -g 1000 trader && \
    useradd -u 1000 -g trader -m -s /bin/bash trader

WORKDIR /app

# Copy application source code
COPY --chown=trader:trader nautilus_trader /app/nautilus_trader
COPY --chown=trader:trader run_live_paper_test.py /app/run_live_paper_test.py
COPY --chown=trader:trader pyproject.toml /app/pyproject.toml
COPY --chown=trader:trader README.md /app/README.md
COPY --chown=trader:trader deployment /app/deployment

# Make entrypoint and healthcheck executable
RUN chmod +x /app/deployment/*.sh /app/deployment/*.py 2>/dev/null || true

USER trader

# Container-level health check fallback
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python3 /app/deployment/healthcheck.py || exit 1

ENTRYPOINT ["/app/deployment/entrypoint.sh"]
CMD ["python3", "run_live_paper_test.py"]
