# syntax=docker/dockerfile:1
# -------------------------
# BUILDER STAGE
# -------------------------
FROM python:3.12-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Install uv
RUN pip install --no-cache-dir uv

# Install dependencies first (caching layer)
COPY pyproject.toml .
# Compile all dependencies (including api, ingest, research extras) into requirements.txt and install
RUN uv pip compile pyproject.toml --all-extras -o requirements.txt && \
    uv pip install --system -r requirements.txt

# -------------------------
# RUNTIME STAGE
# -------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Non-root user
RUN useradd -m -u 1000 appuser

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

COPY --chown=appuser:appuser src/ ./src/

# Copy data directory (containing the DuckDB file) so it is baked into the image
COPY --chown=appuser:appuser data/ ./data/

USER appuser
ENV PYTHONPATH=/app/src

EXPOSE 8000
CMD ["uvicorn", "indiquant.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
