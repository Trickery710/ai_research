"""GET /stats -- System-wide statistics and queue depths."""
from fastapi import APIRouter

import redis

from app.config import Config
from app.db import execute_query_one, execute_query
from app.models import StatsResponse

router = APIRouter()

_redis_client = None


def _get_redis():
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis(
            host=Config.REDIS_HOST,
            port=Config.REDIS_PORT,
            decode_responses=True
        )
    return _redis_client


@router.get("/stats", response_model=StatsResponse)
def get_stats():
    """Return aggregate statistics across the entire system."""
    r = _get_redis()

    total_documents = execute_query_one(
        "SELECT COUNT(*) AS count FROM research.documents"
    )["count"]

    stage_rows = execute_query(
        """SELECT processing_stage, COUNT(*) AS count
           FROM research.documents
           GROUP BY processing_stage""",
        fetch=True
    ) or []
    documents_by_stage = {
        row["processing_stage"]: row["count"] for row in stage_rows
    }

    total_chunks = execute_query_one(
        "SELECT COUNT(*) AS count FROM research.document_chunks"
    )["count"]

    chunks_with_embeddings = execute_query_one(
        """SELECT COUNT(*) AS count FROM research.document_chunks
           WHERE embedding IS NOT NULL"""
    )["count"]

    chunks_evaluated = execute_query_one(
        "SELECT COUNT(*) AS count FROM research.chunk_evaluations"
    )["count"]

    total_dtc = execute_query_one(
        "SELECT COUNT(*) AS count FROM refined.dtc_codes"
    )["count"]

    total_causes = execute_query_one(
        "SELECT COUNT(*) AS count FROM refined.causes"
    )["count"]

    total_steps = execute_query_one(
        "SELECT COUNT(*) AS count FROM refined.diagnostic_steps"
    )["count"]

    queue_names = [
        "jobs:chunk", "jobs:embed", "jobs:evaluate",
        "jobs:extract", "jobs:resolve", "jobs:crawl"
    ]
    queue_depths = {q: r.llen(q) for q in queue_names}

    return StatsResponse(
        total_documents=total_documents,
        documents_by_stage=documents_by_stage,
        total_chunks=total_chunks,
        chunks_with_embeddings=chunks_with_embeddings,
        chunks_evaluated=chunks_evaluated,
        total_dtc_codes=total_dtc,
        total_causes=total_causes,
        total_diagnostic_steps=total_steps,
        queue_depths=queue_depths
    )
