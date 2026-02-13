"""Pydantic request and response models for all API endpoints."""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


# ---- Request Models ----

class IngestRequest(BaseModel):
    title: str
    source_url: Optional[str] = None
    content: str


class CrawlRequest(BaseModel):
    url: str
    max_depth: int = Field(default=1, ge=0, le=3)


class SearchRequest(BaseModel):
    query: str
    limit: int = Field(default=10, ge=1, le=100)
    min_trust: float = Field(default=0.0, ge=0.0, le=1.0)
    min_relevance: float = Field(default=0.0, ge=0.0, le=1.0)


# ---- Response Models ----

class IngestResponse(BaseModel):
    status: str
    id: str


class DocumentResponse(BaseModel):
    id: str
    title: str
    source_url: Optional[str]
    processing_stage: str
    chunk_count: int
    ingestion_timestamp: datetime


class DocumentDetailResponse(DocumentResponse):
    content_hash: str
    mime_type: Optional[str]
    error_message: Optional[str]


class ChunkResponse(BaseModel):
    id: str
    chunk_index: int
    content: str
    trust_score: Optional[float]
    relevance_score: Optional[float]
    automotive_domain: Optional[str]


class SearchResultResponse(BaseModel):
    chunk_id: str
    document_id: str
    document_title: str
    content: str
    similarity: float
    trust_score: Optional[float]
    relevance_score: Optional[float]


class DTCResponse(BaseModel):
    id: str
    code: str
    description: Optional[str]
    category: Optional[str]
    severity: Optional[str]
    confidence_score: float
    source_count: int


class DTCDetailResponse(DTCResponse):
    causes: List[dict]
    diagnostic_steps: List[dict]
    sensors: List[dict]
    tsb_references: List[dict]


class CrawlResponse(BaseModel):
    status: str
    crawl_id: str
    url: str


class StatsResponse(BaseModel):
    total_documents: int
    documents_by_stage: dict
    total_chunks: int
    chunks_with_embeddings: int
    chunks_evaluated: int
    total_dtc_codes: int
    total_causes: int
    total_diagnostic_steps: int
    queue_depths: dict


class HealthResponse(BaseModel):
    status: str
    database: str
    redis: str
    minio: str
