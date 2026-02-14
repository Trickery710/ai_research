# Optimized build for crawler worker with XML dependencies
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install build deps, pip install, remove build deps - all in one layer
COPY crawler/requirements.txt .
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxml2 libxslt1.1 gcc libxml2-dev libxslt-dev \
    && pip install --no-cache-dir -r requirements.txt \
    && apt-get purge -y --auto-remove gcc libxml2-dev libxslt-dev \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser appuser

COPY shared/ ./shared/
COPY crawler/worker.py .

RUN chown -R appuser:appuser /app

USER appuser

CMD ["python", "worker.py"]
