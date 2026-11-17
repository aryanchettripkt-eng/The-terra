# syntax=docker/dockerfile:1
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

# Install essential runtime & geospatial libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install uv for blazing-fast package management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Copy workspace package manifests
COPY pyproject.toml uv.lock ./
COPY core/pyproject.toml ./core/
COPY api/pyproject.toml ./api/
COPY pipeline/pyproject.toml ./pipeline/

# Copy source code
COPY core/ ./core/
COPY api/ ./api/
COPY pipeline/ ./pipeline/
COPY infra/ ./infra/
COPY scripts/ ./scripts/

# Install dependencies into system environment
RUN uv pip install --system -e ./core -e ./api -e ./pipeline

EXPOSE 8000

# Hosts such as Google Cloud Run inject the port to listen on as $PORT; fall back to 8000 locally.
CMD ["sh", "-c", "exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
