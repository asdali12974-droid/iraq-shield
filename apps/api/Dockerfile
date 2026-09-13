# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 `
    PYTHONDONTWRITEBYTECODE=1 `
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update `
    && apt-get install -y --no-install-recommends curl `
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd -m -u 10001 appuser && chown -R appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 `
    CMD curl -fsS "http://localhost:${PORT:-8000}/health" || exit 1

ENTRYPOINT ["./entrypoint.sh"]
CMD ["serve"]