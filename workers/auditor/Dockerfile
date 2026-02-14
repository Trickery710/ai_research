FROM python:3.11-slim
WORKDIR /app
COPY auditor/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY shared/ ./shared/
COPY auditor/worker.py .
COPY auditor/quality_analyzer.py .
COPY auditor/coverage_analyzer.py .
COPY auditor/pipeline_analyzer.py .
COPY auditor/report_generator.py .
CMD ["python", "worker.py"]
