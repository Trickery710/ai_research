"""Document-related API endpoints.

GET /documents           -- List documents (optional stage filter)
GET /documents/{doc_id}  -- Document detail
GET /documents/{doc_id}/chunks -- Document chunks with eval scores
GET /documents/{doc_id}/status -- Processing status + log
"""
from fastapi import APIRouter, HTTPException
from typing import List

from app.db import execute_query, execute_query_one
from app.models import (
    DocumentResponse, DocumentDetailResponse, ChunkResponse
)

router = APIRouter()


@router.get("/documents", response_model=List[DocumentResponse])
def list_documents(stage: str = None, limit: int = 50, offset: int = 0):
    """List documents, optionally filtered by processing_stage."""
    if stage:
        rows = execute_query(
            """SELECT id, title, source_url, processing_stage,
                      chunk_count, ingestion_timestamp
               FROM research.documents
               WHERE processing_stage = %s
               ORDER BY ingestion_timestamp DESC
               LIMIT %s OFFSET %s""",
            (stage, limit, offset), fetch=True
        )
    else:
        rows = execute_query(
            """SELECT id, title, source_url, processing_stage,
                      chunk_count, ingestion_timestamp
               FROM research.documents
               ORDER BY ingestion_timestamp DESC
               LIMIT %s OFFSET %s""",
            (limit, offset), fetch=True
        )
    return [DocumentResponse(**row) for row in (rows or [])]


@router.get("/documents/{doc_id}", response_model=DocumentDetailResponse)
def get_document(doc_id: str):
    """Get full details for a single document."""
    row = execute_query_one(
        """SELECT id, title, source_url, processing_stage, chunk_count,
                  ingestion_timestamp, content_hash, mime_type, error_message
           FROM research.documents WHERE id = %s""",
        (doc_id,)
    )
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentDetailResponse(**row)


@router.get("/documents/{doc_id}/chunks", response_model=List[ChunkResponse])
def get_document_chunks(doc_id: str):
    """Get all chunks for a document, joined with evaluation scores."""
    rows = execute_query(
        """SELECT dc.id, dc.chunk_index, dc.content,
                  ce.trust_score, ce.relevance_score, ce.automotive_domain
           FROM research.document_chunks dc
           LEFT JOIN research.chunk_evaluations ce ON dc.id = ce.chunk_id
           WHERE dc.document_id = %s
           ORDER BY dc.chunk_index""",
        (doc_id,), fetch=True
    )
    return [ChunkResponse(**row) for row in (rows or [])]


@router.get("/documents/{doc_id}/status")
def get_document_status(doc_id: str):
    """Get the current processing stage and full processing log."""
    doc = execute_query_one(
        """SELECT id, title, processing_stage, error_message
           FROM research.documents WHERE id = %s""",
        (doc_id,)
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    logs = execute_query(
        """SELECT stage, status, message, duration_ms, created_at
           FROM research.processing_log
           WHERE document_id = %s
           ORDER BY created_at""",
        (doc_id,), fetch=True
    )

    return {
        "document_id": str(doc["id"]),
        "title": doc["title"],
        "current_stage": doc["processing_stage"],
        "error_message": doc["error_message"],
        "processing_log": logs or []
    }
