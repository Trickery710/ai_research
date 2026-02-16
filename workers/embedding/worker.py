"""Embedding Worker.

For each document, fetches all its chunks from PostgreSQL,
calls the Ollama embedding API (llm-embed on GPU 0) to generate
768-dimension vectors via nomic-embed-text, and stores the vectors
in the embedding column of research.document_chunks.

Queue: jobs:embed
Payload: document UUID string
Next: jobs:evaluate
"""
import sys
import time
import traceback

sys.path.insert(0, "/app")

from shared.config import Config
from shared.redis_client import pop_job
from shared.db import get_connection, return_connection
from shared.ollama_client import generate_embedding, ensure_model_available
from shared.pipeline import (
    update_document_stage, log_processing, advance_to_next_stage
)


def process_document(doc_id):
    """Generate and store embeddings for all chunks of a document."""
    start_time = time.time()

    update_document_stage(doc_id, "embedding")
    log_processing(doc_id, "embedding", "started")

    # Fetch all chunks for this document
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT id, content FROM research.document_chunks
               WHERE document_id = %s ORDER BY chunk_index""",
            (doc_id,)
        )
        chunks = cur.fetchall()
    finally:
        return_connection(conn)

    if not chunks:
        raise ValueError(f"No chunks found for document {doc_id}")

    # Generate embedding for each chunk and store it
    embedded_count = 0
    for chunk_id, content in chunks:
        embedding = generate_embedding(content)

        conn = get_connection()
        try:
            cur = conn.cursor()
            # pgvector accepts Python list cast to string for VECTOR type
            cur.execute(
                "UPDATE research.document_chunks SET embedding = %s WHERE id = %s",
                (str(embedding), chunk_id)
            )
            conn.commit()
            embedded_count += 1
        except Exception:
            conn.rollback()
            raise
        finally:
            return_connection(conn)

    duration_ms = int((time.time() - start_time) * 1000)
    log_processing(doc_id, "embedding", "completed",
                   f"Embedded {embedded_count} chunks", duration_ms)
    advance_to_next_stage(doc_id, "embedded", "evaluating")
    print(f"[embedding] doc={doc_id} embedded={embedded_count} ms={duration_ms}")


def main():
    from shared.graceful import GracefulShutdown, wait_for_db, wait_for_redis

    shutdown = GracefulShutdown()

    print(f"[embedding] Worker started. Queue={Config.WORKER_QUEUE} "
          f"Ollama={Config.OLLAMA_BASE_URL} Model={Config.EMBEDDING_MODEL}")

    wait_for_db()
    wait_for_redis()

    # Pull model if not yet available (blocks until done)
    ensure_model_available(Config.EMBEDDING_MODEL)

    while shutdown.is_running():
        try:
            job = pop_job(Config.WORKER_QUEUE, timeout=Config.POLL_TIMEOUT)
            if job:
                process_document(job.strip())
        except Exception as e:
            print(f"[embedding] ERROR: {e}")
            traceback.print_exc()
            try:
                if job:
                    update_document_stage(job.strip(), "error", str(e)[:500])
                    log_processing(job.strip(), "embedding", "failed", str(e)[:500])
            except Exception:
                pass
        time.sleep(0.1)

    shutdown.cleanup()


if __name__ == "__main__":
    main()
