# ══════════════════════════════════════════════════════════════
# Scraper service — Python 3.12 slim base
# ══════════════════════════════════════════════════════════════

FROM python:3.12-slim AS base

WORKDIR /app

# ── System dependencies for curl_cffi (libcurl) ─────────────────
RUN apt-get update && \
    apt-get install -y --no-install-recommends libcurl4 && \
    rm -rf /var/lib/apt/lists/*

# ── Install shared package ──────────────────────────────────────
COPY shared /app/shared
RUN pip install --no-cache-dir -r /app/shared/requirements.txt

# ── Install service-specific dependencies ───────────────────────
COPY services/scraper/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# ── Copy service source ─────────────────────────────────────────
COPY services/scraper/src /app/src

# ── Default entrypoint ──────────────────────────────────────────
ENTRYPOINT ["python", "-m", "src.main"]
