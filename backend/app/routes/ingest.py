"""POST /ingest -- Ingest a document into the processing pipeline.

Stores raw content in MinIO, metadata in PostgreSQL, and pushes the
document UUID to the jobs:chunk Redis queue.
"""
from fastapi import APIRouter, HTTPException
import hashlib
import uuid
import io

import redis
from minio import Minio

from app.config import Config
from app.db import get_connection, return_connection
from app.models import IngestRequest, IngestResponse

router = APIRouter()

_redis_client = None
_minio_client = None


def _get_redis():
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis(
            host=Config.REDIS_HOST,
            port=Config.REDIS_PORT,
            decode_responses=True
        )
    return _redis_client


def _get_minio():
    global _minio_client
    if _minio_client is None:
        _minio_client = Minio(
            Config.MINIO_ENDPOINT,
            access_key=Config.MINIO_ACCESS_KEY,
            secret_key=Config.MINIO_SECRET_KEY,
            secure=False
        )
        if not _minio_client.bucket_exists(Config.MINIO_BUCKET):
            _minio_client.make_bucket(Config.MINIO_BUCKET)
    return _minio_client


@router.post("/ingest", response_model=IngestResponse)
def ingest(doc: IngestRequest):
    """Ingest a document.

    1. Generate a UUID for the document.
    2. Compute SHA-256 hash of the content.
    3. Store raw content in MinIO at key "raw/{doc_id}".
    4. Insert metadata row into research.documents.
    5. Push doc_id to Redis queue "jobs:chunk".
    """
    doc_id = str(uuid.uuid4())
    content_hash = hashlib.sha256(doc.content.encode("utf-8")).hexdigest()
    minio_key = f"raw/{doc_id}"

    # Store content in MinIO
    try:
        data = doc.content.encode("utf-8")
        _get_minio().put_object(
            Config.MINIO_BUCKET,
            minio_key,
            io.BytesIO(data),
            length=len(data),
            content_type="text/plain"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"MinIO storage failed: {e}"
        )

    # Insert document metadata into PostgreSQL
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO research.documents
               (id, title, source_url, content_hash, mime_type,
                minio_bucket, minio_key, processing_stage)
               VALUES (%s, %s, %s, %s, 'text/plain', %s, %s, 'pending')""",
            (doc_id, doc.title, doc.source_url, content_hash,
             Config.MINIO_BUCKET, minio_key)
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise HTTPException(
            status_code=500, detail=f"Database insert failed: {e}"
        )
    finally:
        return_connection(conn)

    # Push to chunking queue (just the UUID, not the content)
    _get_redis().lpush("jobs:chunk", doc_id)

    return IngestResponse(status="queued", id=doc_id)
