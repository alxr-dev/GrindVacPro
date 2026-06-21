# ══════════════════════════════════════════════════════════════
# Analyzer service — Python 3.12 slim base (Network I/O)
# ══════════════════════════════════════════════════════════════

FROM python:3.12-slim AS base

WORKDIR /app

# ── Install shared package ──────────────────────────────────────
COPY shared /app/shared
RUN pip install --no-cache-dir -r /app/shared/requirements.txt

# ── Install service-specific dependencies ───────────────────────
COPY services/analyzer/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# ── Copy service source ─────────────────────────────────────────
COPY services/analyzer/src /app/src

# ── Default entrypoint ──────────────────────────────────────────
CMD ["python", "-m", "src.worker"]
