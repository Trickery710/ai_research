FROM python:3.11-slim
WORKDIR /app
COPY orchestrator/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY shared/ ./shared/
COPY orchestrator/worker.py .
COPY orchestrator/task_manager.py .
COPY orchestrator/resource_monitor.py .
COPY orchestrator/planner.py .
CMD ["python", "worker.py"]
