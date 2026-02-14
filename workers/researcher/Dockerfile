FROM python:3.11-slim
WORKDIR /app
COPY researcher/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY shared/ ./shared/
COPY researcher/worker.py .
COPY researcher/query_generator.py .
COPY researcher/url_evaluator.py .
COPY researcher/source_registry.py .
CMD ["python", "worker.py"]
