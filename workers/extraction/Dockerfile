FROM python:3.11-slim
WORKDIR /app
COPY extraction/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY shared/ ./shared/
COPY extraction/worker.py .
CMD ["python", "worker.py"]
