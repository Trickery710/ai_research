FROM python:3.11-slim
WORKDIR /app
COPY conflict/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY shared/ ./shared/
COPY conflict/worker.py .
CMD ["python", "worker.py"]
