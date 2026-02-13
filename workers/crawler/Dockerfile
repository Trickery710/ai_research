FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxml2-dev libxslt-dev && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY crawler/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY shared/ ./shared/
COPY crawler/worker.py .
CMD ["python", "worker.py"]
