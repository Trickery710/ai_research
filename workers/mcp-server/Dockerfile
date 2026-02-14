FROM python:3.11-slim
WORKDIR /app
COPY mcp-server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY shared/ ./shared/
COPY mcp-server/server.py .
COPY mcp-server/tools.py .
EXPOSE 8002
CMD ["python", "server.py"]
