# ══════════════════════════════════════════════════════════════
# Dashboard service — Streamlit frontend (Docker)
# ══════════════════════════════════════════════════════════════

FROM python:3.12-slim

WORKDIR /app

# Install shared dependencies (cached layer)
COPY shared /app/shared
RUN pip install --no-cache-dir -r /app/shared/requirements.txt

# Install dashboard dependencies
COPY services/dashboard/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy dashboard source
COPY services/dashboard/src /app/src

# Expose Streamlit default port
EXPOSE 8501

ENV PYTHONPATH=/app

# Run Streamlit
CMD ["streamlit", "run", "src/app.py", "--server.headless=true", "--server.port=8501", "--server.address=0.0.0.0"]
