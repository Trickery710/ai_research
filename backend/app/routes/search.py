"""POST /search -- Semantic vector search across document chunks.

Generates an embedding for the query string via the llm-embed Ollama
instance, then uses pgvector cosine distance to find similar chunks.
"""
from fastapi import APIRouter, HTTPException
from typing import List

import requests as http_requests

from app.config import Config
from app.db import get_connection, return_connection
from app.models import SearchRequest, SearchResultResponse

router = APIRouter()


def _get_query_embedding(query_text):
    """Call Ollama embedding API to vectorize the search query."""
    try:
        resp = http_requests.post(
            f"{Config.OLLAMA_EMBED_URL}/api/embeddings",
            json={
                "model": Config.EMBEDDING_MODEL,
                "prompt": query_text
            },
            timeout=30
        )
        resp.raise_for_status()
        return resp.json()["embedding"]
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Embedding service unavailable: {e}"
        )


@router.post("/search", response_model=List[SearchResultResponse])
def vector_search(req: SearchRequest):
    """Semantic search.

    1. Embed the query text via Ollama.
    2. Query pgvector for the closest chunks by cosine distance.
    3. Optionally filter by min_trust and min_relevance thresholds.
    4. Return ranked results.
    """
    embedding = _get_query_embedding(req.query)
    embedding_str = str(embedding)

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT
                 dc.id AS chunk_id,
                 dc.document_id,
                 d.title AS document_title,
                 dc.content,
                 1 - (dc.embedding <=> %s::vector) AS similarity,
                 ce.trust_score,
                 ce.relevance_score
               FROM research.document_chunks dc
               JOIN research.documents d ON dc.document_id = d.id
               LEFT JOIN research.chunk_evaluations ce ON dc.id = ce.chunk_id
               WHERE dc.embedding IS NOT NULL
                 AND (ce.trust_score IS NULL OR ce.trust_score >= %s)
                 AND (ce.relevance_score IS NULL OR ce.relevance_score >= %s)
               ORDER BY dc.embedding <=> %s::vector
               LIMIT %s""",
            (embedding_str, req.min_trust, req.min_relevance,
             embedding_str, req.limit)
        )
        rows = cur.fetchall()

        results = []
        for row in rows:
            results.append(SearchResultResponse(
                chunk_id=str(row[0]),
                document_id=str(row[1]),
                document_title=row[2],
                content=row[3],
                similarity=round(float(row[4]), 4) if row[4] else 0.0,
                trust_score=float(row[5]) if row[5] is not None else None,
                relevance_score=float(row[6]) if row[6] is not None else None
            ))
        return results
    finally:
        return_connection(conn)
