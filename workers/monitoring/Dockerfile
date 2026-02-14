FROM python:3.11-slim

WORKDIR /app

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

# Expose metrics endpoint
EXPOSE 8001

CMD ["python", "worker.py"]
