"""Chunking Worker.

Reads raw document content from MinIO, splits it into overlapping
500-character chunks, inserts them into research.document_chunks,
then pushes the document to the embedding queue.

Queue: jobs:chunk
Payload: document UUID string
Next: jobs:embed
"""
import sys
import time
import traceback
import uuid as uuid_mod

sys.path.insert(0, "/app")

from shared.config import Config
from shared.redis_client import pop_job
from shared.minio_client import get_content
from shared.db import get_connection, return_connection
from shared.pipeline import (
    update_document_stage, log_processing, advance_to_next_stage
)

CHUNK_SIZE = 500
CHUNK_OVERLAP = 50


def chunk_text(text, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    """Split text into overlapping character-based chunks.

    Returns:
        list[dict]: Each dict has keys 'content', 'char_start', 'char_end'.
    """
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        chunks.append({
            "content": text[start:end],
            "char_start": start,
            "char_end": end
        })
        if end >= len(text):
            break
        start += size - overlap
    return chunks


def process_document(doc_id):
    """Chunk a single document and store results in PostgreSQL."""
    start_time = time.time()

    update_document_stage(doc_id, "chunking")
    log_processing(doc_id, "chunking", "started")

    # Look up the MinIO key for this document
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT minio_key FROM research.documents WHERE id = %s",
            (doc_id,)
        )
        row = cur.fetchone()
        if not row or not row[0]:
            raise ValueError(f"Document {doc_id} has no minio_key")
        minio_key = row[0]
    finally:
        return_connection(conn)

    # Fetch the full text from MinIO
    content = get_content(minio_key)

    # Split into chunks
    chunks = chunk_text(content)

    # Batch-insert all chunks
    conn = get_connection()
    try:
        cur = conn.cursor()
        for i, chunk in enumerate(chunks):
            cur.execute(
                """INSERT INTO research.document_chunks
                   (id, document_id, chunk_index, content, char_start, char_end)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT (document_id, chunk_index) DO UPDATE
                   SET content = EXCLUDED.content,
                       char_start = EXCLUDED.char_start,
                       char_end = EXCLUDED.char_end""",
                (str(uuid_mod.uuid4()), doc_id, i,
                 chunk["content"], chunk["char_start"], chunk["char_end"])
            )
        cur.execute(
            "UPDATE research.documents SET chunk_count = %s WHERE id = %s",
            (len(chunks), doc_id)
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        return_connection(conn)

    duration_ms = int((time.time() - start_time) * 1000)
    log_processing(doc_id, "chunking", "completed",
                   f"Created {len(chunks)} chunks", duration_ms)
    advance_to_next_stage(doc_id, "chunked", "embedding")
    print(f"[chunking] doc={doc_id} chunks={len(chunks)} ms={duration_ms}")


def main():
    from shared.graceful import GracefulShutdown, wait_for_db, wait_for_redis

    shutdown = GracefulShutdown()

    print(f"[chunking] Worker started. Queue={Config.WORKER_QUEUE} "
          f"Next={Config.NEXT_QUEUE}")

    wait_for_db()
    wait_for_redis()

    while shutdown.is_running():
        try:
            job = pop_job(Config.WORKER_QUEUE, timeout=Config.POLL_TIMEOUT)
            if job:
                process_document(job.strip())
        except Exception as e:
            print(f"[chunking] ERROR: {e}")
            traceback.print_exc()
            try:
                if job:
                    update_document_stage(job.strip(), "error", str(e)[:500])
                    log_processing(job.strip(), "chunking", "failed", str(e)[:500])
            except Exception:
                pass
        time.sleep(0.1)

    shutdown.cleanup()


if __name__ == "__main__":
    main()
