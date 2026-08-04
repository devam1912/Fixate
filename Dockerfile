# Multi-stage production build for Fixate Self-Healing Agent Application

# Stage 1: Build Vite React Dashboard Frontend
# Debian-based (not alpine) so the Node runtime copied into the glibc production
# stage below is binary-compatible; a musl-linked node will not execute there.
FROM node:20-bookworm-slim AS frontend-builder
WORKDIR /app/dashboard

COPY dashboard/package.json dashboard/package-lock.json* ./
RUN npm ci

COPY dashboard/ ./
RUN npm run build

# Stage 2: Production Python Backend & Runtime Environment
FROM python:3.11-slim AS production

# Install essential system dependencies (Git for cloning, GCC for C extensions)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    gcc \
    g++ \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Node.js is required to verify JavaScript/TypeScript repairs: patches are proved by
# executing the target repository's own Jest or Vitest suite, which cannot run
# without a JS runtime. (Parsing does not need Node -- tree-sitter handles that from
# Python -- but verification does.)
COPY --from=frontend-builder /usr/local/bin/node /usr/local/bin/node
COPY --from=frontend-builder /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -sf /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -sf /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && node --version && npm --version

WORKDIR /app

# Copy dependency specifications & install Python dependencies
COPY requirements.txt pyproject.toml README.md ./
RUN pip install --no-cache-dir uv && \
    uv pip install --system --no-cache -r requirements.txt && \
    uv pip install --system --no-cache -e .

# Copy backend source code & sample benchmark repos
COPY fixate/ ./fixate/
COPY sample_repos/ ./sample_repos/

# Copy built React SPA static bundle from Stage 1 into /app/dashboard/dist
COPY --from=frontend-builder /app/dashboard/dist ./dashboard/dist

# Run as an unprivileged user. This container clones untrusted repositories and
# prepares their dependencies, and package installation executes arbitrary code
# from build hooks; that must not happen as root.
RUN useradd --create-home --uid 10001 fixate \
    && mkdir -p /app/data /app/telemetry_logs /app/chroma_db \
    && chown -R fixate:fixate /app
USER fixate

# Expose production port 8000
EXPOSE 8000

# Environment configuration defaults
ENV PYTHONUNBUFFERED=1 \
    PORT=8000 \
    APP_ENV=production

# Healthcheck for orchestration readiness
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

# Launch production server running backend API and serving frontend SPA
CMD ["sh", "-c", "uvicorn fixate.api.server:app --host 0.0.0.0 --port ${PORT:-8000}"]
