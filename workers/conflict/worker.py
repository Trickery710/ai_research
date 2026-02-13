"""Conflict Resolution Worker.

After extraction completes for a document, this worker:
1. Recalculates confidence_score for all DTC codes using
   source_count and average trust_score from linked source chunks.
2. Deduplicates causes (same DTC + same description).
3. Deduplicates diagnostic steps (same DTC + same description).
4. Marks the document as 'complete' (terminal stage).

Queue: jobs:resolve
Payload: document UUID string
Next: (none -- terminal)
"""
import sys
import time
import traceback

sys.path.insert(0, "/app")

from shared.config import Config
from shared.redis_client import pop_job
from shared.db import get_connection, return_connection
from shared.pipeline import (
    update_document_stage, log_processing
)


def recalculate_dtc_confidence():
    """Recalculate confidence_score for all DTC codes.

    Formula: confidence = min(1.0, 0.3 * source_factor + 0.7 * avg_trust)
    where source_factor = min(1.0, source_count / 5.0)

    A DTC with 5+ sources and trust_score=1.0 reaches confidence=1.0.
    A DTC with 1 source and trust_score=0.5 gets confidence=0.41.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE refined.dtc_codes d
            SET confidence_score = LEAST(1.0,
                0.3 * LEAST(1.0, d.source_count::float / 5.0) +
                0.7 * COALESCE(
                    (SELECT AVG(ce.trust_score)
                     FROM refined.dtc_sources ds
                     JOIN research.chunk_evaluations ce
                         ON ds.chunk_id = ce.chunk_id
                     WHERE ds.dtc_id = d.id),
                    0.5
                )
            ),
            updated_at = NOW()
        """)
        updated = cur.rowcount
        conn.commit()
        return updated
    except Exception:
        conn.rollback()
        raise
    finally:
        return_connection(conn)


def deduplicate_causes():
    """Remove duplicate causes sharing the same DTC and description text.

    Keeps the row with the lower id (earlier insertion).
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            DELETE FROM refined.causes a
            USING refined.causes b
            WHERE a.dtc_id = b.dtc_id
              AND LOWER(TRIM(a.description)) = LOWER(TRIM(b.description))
              AND a.id > b.id
        """)
        deleted = cur.rowcount
        conn.commit()
        return deleted
    except Exception:
        conn.rollback()
        raise
    finally:
        return_connection(conn)


def deduplicate_diagnostic_steps():
    """Remove duplicate diagnostic steps sharing the same DTC and description.

    Keeps the row with the lower id.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            DELETE FROM refined.diagnostic_steps a
            USING refined.diagnostic_steps b
            WHERE a.dtc_id = b.dtc_id
              AND LOWER(TRIM(a.description)) = LOWER(TRIM(b.description))
              AND a.id > b.id
        """)
        deleted = cur.rowcount
        conn.commit()
        return deleted
    except Exception:
        conn.rollback()
        raise
    finally:
        return_connection(conn)


def process_document(doc_id):
    """Run conflict resolution for a document, then mark it complete."""
    start_time = time.time()

    update_document_stage(doc_id, "resolving")
    log_processing(doc_id, "resolving", "started")

    dtc_updated = recalculate_dtc_confidence()
    causes_deduped = deduplicate_causes()
    steps_deduped = deduplicate_diagnostic_steps()

    duration_ms = int((time.time() - start_time) * 1000)
    message = (
        f"DTC scores updated: {dtc_updated}, "
        f"causes deduped: {causes_deduped}, "
        f"steps deduped: {steps_deduped}"
    )
    log_processing(doc_id, "resolving", "completed", message, duration_ms)

    # Terminal stage: mark document as complete
    update_document_stage(doc_id, "complete")
    print(f"[conflict] doc={doc_id} {message} ms={duration_ms}")


def main():
    print(f"[conflict] Worker started. Queue={Config.WORKER_QUEUE}")

    while True:
        try:
            job = pop_job(Config.WORKER_QUEUE, timeout=Config.POLL_TIMEOUT)
            if job:
                process_document(job.strip())
        except Exception as e:
            print(f"[conflict] ERROR: {e}")
            traceback.print_exc()
            try:
                if job:
                    update_document_stage(job.strip(), "error", str(e)[:500])
                    log_processing(job.strip(), "resolving", "failed",
                                   str(e)[:500])
            except Exception:
                pass
        time.sleep(0.1)


if __name__ == "__main__":
    main()
