# Optimized build for auditor worker
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
COPY auditor/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared modules
COPY shared/ ./shared/

# Copy auditor modules
COPY auditor/worker.py .
COPY auditor/quality_analyzer.py .
COPY auditor/coverage_analyzer.py .
COPY auditor/pipeline_analyzer.py .
COPY auditor/report_generator.py .

# Remove any Python cache files
RUN find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true && \
    find . -type f -name "*.pyc" -delete 2>/dev/null || true

# Change ownership to non-root user
RUN chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

CMD ["python", "worker.py"]
