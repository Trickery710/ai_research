"""Centralized configuration from environment variables."""
import os


class Config:
    DATABASE_URL = os.environ.get(
        "DATABASE_URL",
        "postgresql://refinery:refinery@postgres:5432/refinery"
    )
    REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
    REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))

    MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "minio:9000")
    MINIO_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY", "minioadmin")
    MINIO_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY", "minioadmin")
    MINIO_BUCKET = os.environ.get("MINIO_BUCKET", "documents")

    OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://llm-embed:11434")
    EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "nomic-embed-text")
    REASONING_MODEL = os.environ.get("REASONING_MODEL", "llama3")

    WORKER_QUEUE = os.environ.get("WORKER_QUEUE", "jobs:default")
    NEXT_QUEUE = os.environ.get("NEXT_QUEUE", "")
    POLL_TIMEOUT = int(os.environ.get("POLL_TIMEOUT", 5))
