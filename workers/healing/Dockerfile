FROM python:3.11-slim

WORKDIR /app

# Install Docker CLI (for container restarts)
RUN apt-get update && apt-get install -y \
    docker.io \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Optional: Install Claude Code CLI (controlled via build arg)
ARG CLAUDE_CODE_ENABLED=false
RUN if [ "$CLAUDE_CODE_ENABLED" = "true" ]; then \
        curl -fsSL https://claude.com/cli/install.sh | sh; \
    fi

# Install Python dependencies
COPY healing/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared modules
COPY shared/ ./shared/

# Copy healing modules
COPY healing/worker.py .
COPY healing/analyzer.py .
COPY healing/executor.py .
COPY healing/safety.py .
COPY healing/audit_logger.py .

CMD ["python", "worker.py"]
