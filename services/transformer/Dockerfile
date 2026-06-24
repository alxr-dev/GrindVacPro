# ══════════════════════════════════════════════════════════════
# Transformer service — CPU-only, lightweight build
# ══════════════════════════════════════════════════════════════

# ── Stage 1: Builder — install deps + bake model into image ──────
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build essentials for compiling wheel packages
# RUN apt-get update && apt-get install -y --no-install-recommends \
#     build-essential \
#     && rm -rf /var/lib/apt/lists/*

# Install shared dependencies first (cached layer)
COPY shared /app/shared
RUN pip install --no-cache-dir -r /app/shared/requirements.txt

# Install CPU-only PyTorch (3x smaller than GPU version)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Install sentence-transformers (CPU-only, no CUDA deps)
RUN pip install --no-cache-dir sentence-transformers==5.6.0

# Install remaining service-specific deps
COPY services/transformer/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Bake the model into the image — no download at startup
ENV HF_HOME=/app/.cache/huggingface
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('cointegrated/rubert-tiny2')"

# Smoke test: verify cached model loads correctly in offline mode
    RUN HF_HUB_OFFLINE=1 python -c "from sentence_transformers import SentenceTransformer; m = SentenceTransformer('cointegrated/rubert-tiny2'); print('Model loaded OK, dim=', m.get_embedding_dimension())"

# ── Stage 2: Runtime — slim image without build tools ────────────
FROM python:3.12-slim

WORKDIR /app

# Copy installed packages and cached model from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /app/.cache /app/.cache

# Set env vars for offline model loading
ENV HF_HOME=/app/.cache/huggingface
ENV HF_HUB_OFFLINE=1

# Copy shared package source
COPY shared /app/shared

# Copy service source
COPY services/transformer/src /app/src

# Default entrypoint — use arq CLI to run the worker
CMD ["arq", "src.worker.WorkerSettings"]
