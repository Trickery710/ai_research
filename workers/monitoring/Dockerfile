# Optimized build for monitoring worker
FROM python:3.11-slim-bookworm

# Set Python environment variables to optimize runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Create non-root user for security
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Install dependencies
COPY monitoring/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared modules
COPY shared/ ./shared/

# Copy monitoring modules
COPY monitoring/worker.py .
COPY monitoring/detectors.py .
COPY monitoring/metrics_collector.py .
COPY monitoring/http_server.py .

# Remove any Python cache files
RUN find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true && \
    find . -type f -name "*.pyc" -delete 2>/dev/null || true

# Change ownership to non-root user
RUN chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Expose metrics endpoint
EXPOSE 8001

# Health check for metrics endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8001/metrics', timeout=5)" || exit 1

CMD ["python", "worker.py"]
