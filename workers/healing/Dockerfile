# Multi-stage build for healing worker - extract Docker CLI only
FROM docker:27-cli AS docker-cli

# Runtime stage
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Copy only Docker CLI binary from official image
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker

# Create non-root user with docker group for socket access
RUN groupadd -r appuser && groupadd -r docker && \
    useradd -r -g appuser -G docker appuser

COPY healing/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/ ./shared/
COPY healing/worker.py .
COPY healing/analyzer.py .
COPY healing/executor.py .
COPY healing/safety.py .
COPY healing/audit_logger.py .

RUN find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

RUN chown -R appuser:appuser /app

USER appuser

CMD ["python", "worker.py"]
