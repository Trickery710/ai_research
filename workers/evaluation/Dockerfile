FROM python:3.11-slim
WORKDIR /app
COPY evaluation/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY shared/ ./shared/
COPY evaluation/worker.py .
CMD ["python", "worker.py"]
