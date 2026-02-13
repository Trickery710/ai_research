"""Pipeline stage management: transitions, logging, document lookups."""
import time
from shared.db import execute_query, execute_query_one
from shared.redis_client import push_job
from shared.config import Config


def update_document_stage(doc_id, stage, error_message=None):
    """Set the processing_stage on a document row.

    Args:
        doc_id: Document UUID string.
        stage: New processing stage string.
        error_message: Optional error text (set when stage='error').
    """
    if error_message:
        execute_query(
            """UPDATE research.documents
               SET processing_stage = %s, error_message = %s, updated_at = NOW()
               WHERE id = %s""",
            (stage, error_message, doc_id)
        )
    else:
        execute_query(
            """UPDATE research.documents
               SET processing_stage = %s, updated_at = NOW()
               WHERE id = %s""",
            (stage, doc_id)
        )


def log_processing(doc_id, stage, status, message=None, duration_ms=None):
    """Insert a row into research.processing_log.

    Args:
        doc_id: Document UUID string.
        stage: Pipeline stage name (e.g. 'chunking').
        status: 'started', 'completed', or 'failed'.
        message: Optional details string.
        duration_ms: Optional elapsed time in milliseconds.
    """
    execute_query(
        """INSERT INTO research.processing_log
           (document_id, stage, status, message, duration_ms)
           VALUES (%s, %s, %s, %s, %s)""",
        (doc_id, stage, status, message, duration_ms)
    )


def advance_to_next_stage(doc_id, completed_stage, next_stage_label,
                          next_queue=None):
    """Mark a stage as done and push the document to the next queue.

    If there is no next queue (terminal stage), the document stage
    is set to completed_stage and no job is pushed.

    Args:
        doc_id: Document UUID string.
        completed_stage: Stage label for the completed state (e.g. 'chunked').
        next_stage_label: Stage label for the next state (e.g. 'embedding').
        next_queue: Override queue name. Defaults to Config.NEXT_QUEUE.
    """
    queue = next_queue or Config.NEXT_QUEUE
    if queue:
        update_document_stage(doc_id, next_stage_label)
        push_job(queue, doc_id)
    else:
        update_document_stage(doc_id, completed_stage)


def get_document_info(doc_id):
    """Fetch basic document metadata.

    Returns:
        Tuple of (id, title, source_url, content_hash, minio_key, processing_stage)
        or None if not found.
    """
    return execute_query_one(
        """SELECT id, title, source_url, content_hash, minio_key, processing_stage
           FROM research.documents WHERE id = %s""",
        (doc_id,)
    )
