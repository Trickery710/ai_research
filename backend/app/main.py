"""FastAPI application entry point.

Registers all route modules and provides the /health endpoint.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import psycopg2
import redis
from minio import Minio

from app.config import Config
from app.models import HealthResponse
from app.routes import ingest, search, documents, dtc, crawl, stats, orchestration

app = FastAPI(
    title="AI Research Refinery v2",
    description="Self-Hosted Automotive Knowledge Engine API",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register route modules
app.include_router(ingest.router, tags=["Ingestion"])
app.include_router(search.router, tags=["Search"])
app.include_router(documents.router, tags=["Documents"])
app.include_router(dtc.router, tags=["DTC Codes"])
app.include_router(crawl.router, tags=["Crawler"])
app.include_router(stats.router, tags=["Statistics"])
app.include_router(orchestration.router, tags=["Orchestration"])


@app.get("/health", response_model=HealthResponse)
def health():
    """Health check -- verifies connectivity to Postgres, Redis, and MinIO."""
    db_status = "unknown"
    redis_status = "unknown"
    minio_status = "unknown"

    try:
        conn = psycopg2.connect(Config.DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT 1")
        conn.close()
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {e}"

    try:
        r = redis.Redis(host=Config.REDIS_HOST, port=Config.REDIS_PORT)
        r.ping()
        redis_status = "connected"
    except Exception as e:
        redis_status = f"error: {e}"

    try:
        client = Minio(
            Config.MINIO_ENDPOINT,
            access_key=Config.MINIO_ACCESS_KEY,
            secret_key=Config.MINIO_SECRET_KEY,
            secure=False
        )
        client.list_buckets()
        minio_status = "connected"
    except Exception as e:
        minio_status = f"error: {e}"

    overall = "running" if all(
        s == "connected" for s in [db_status, redis_status, minio_status]
    ) else "degraded"

    return HealthResponse(
        status=overall,
        database=db_status,
        redis=redis_status,
        minio=minio_status
    )
