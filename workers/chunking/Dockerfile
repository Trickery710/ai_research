FROM python:3.11-slim
WORKDIR /app
COPY chunking/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY shared/ ./shared/
COPY chunking/worker.py .
CMD ["python", "worker.py"]
