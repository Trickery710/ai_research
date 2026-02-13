FROM python:3.11-slim
WORKDIR /app
COPY embedding/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY shared/ ./shared/
COPY embedding/worker.py .
CMD ["python", "worker.py"]
