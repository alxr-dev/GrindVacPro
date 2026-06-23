# Telegram Bot service — Python 3.12 slim base

FROM python:3.12-slim AS base

WORKDIR /app

# Install shared package
COPY shared /app/shared
RUN pip install --no-cache-dir -r /app/shared/requirements.txt

# Install service-specific dependencies
COPY services/telegram_bot/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy service source
COPY services/telegram_bot/src /app/src

# Entry point: run both aiogram polling and arq worker
CMD ["python", "-m", "src.main"]
