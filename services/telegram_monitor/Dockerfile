# ══════════════════════════════════════════════════════════════
# Telegram Monitor service — Python 3.12 slim base
# ══════════════════════════════════════════════════════════════

FROM python:3.12-slim AS base

WORKDIR /app

# ── Install shared package ──────────────────────────────────────
COPY shared /app/shared
RUN pip install --no-cache-dir -r /app/shared/requirements.txt

# ── Install service-specific dependencies ───────────────────────
COPY services/telegram_monitor/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# ── Copy service source ─────────────────────────────────────────
COPY services/telegram_monitor/src /app/src

# ── Default entrypoint ──────────────────────────────────────────
ENTRYPOINT ["python", "-m", "src.main"]