-- ==========================================================
-- AI Research Refinery v2 - Complete Database Schema
-- ==========================================================

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ==========================================================
-- RESEARCH SCHEMA (Raw / Processing Layer)
-- ==========================================================
CREATE SCHEMA IF NOT EXISTS research;

CREATE TABLE IF NOT EXISTS research.documents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title TEXT NOT NULL,
    source_url TEXT,
    content_hash TEXT NOT NULL,
    mime_type TEXT DEFAULT 'text/plain',
    minio_bucket TEXT DEFAULT 'documents',
    minio_key TEXT,
    processing_stage TEXT NOT NULL DEFAULT 'pending',
    error_message TEXT,
    chunk_count INT DEFAULT 0,
    ingestion_timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_documents_stage
    ON research.documents(processing_stage);
CREATE INDEX IF NOT EXISTS idx_documents_hash
    ON research.documents(content_hash);

CREATE TABLE IF NOT EXISTS research.document_chunks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id UUID NOT NULL REFERENCES research.documents(id) ON DELETE CASCADE,
    chunk_index INT NOT NULL,
    content TEXT NOT NULL,
    char_start INT,
    char_end INT,
    token_count INT,
    embedding VECTOR(768),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(document_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_chunks_document
    ON research.document_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_embedding
    ON research.document_chunks USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS research.chunk_evaluations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    chunk_id UUID NOT NULL REFERENCES research.document_chunks(id) ON DELETE CASCADE,
    trust_score FLOAT NOT NULL CHECK (trust_score >= 0 AND trust_score <= 1),
    relevance_score FLOAT NOT NULL CHECK (relevance_score >= 0 AND relevance_score <= 1),
    automotive_domain TEXT,
    reasoning TEXT,
    model_used TEXT,
    evaluated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(chunk_id)
);

CREATE INDEX IF NOT EXISTS idx_evaluations_chunk
    ON research.chunk_evaluations(chunk_id);
CREATE INDEX IF NOT EXISTS idx_evaluations_scores
    ON research.chunk_evaluations(trust_score, relevance_score);

CREATE TABLE IF NOT EXISTS research.crawl_queue (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    url TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    depth INT DEFAULT 0,
    max_depth INT DEFAULT 1,
    parent_url TEXT,
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE,
    UNIQUE(url)
);

CREATE INDEX IF NOT EXISTS idx_crawl_status
    ON research.crawl_queue(status);

CREATE TABLE IF NOT EXISTS research.processing_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id UUID REFERENCES research.documents(id) ON DELETE CASCADE,
    stage TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT,
    duration_ms INT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_proclog_document
    ON research.processing_log(document_id);

-- ==========================================================
-- REFINED SCHEMA (Structured Knowledge Layer)
-- ==========================================================
CREATE SCHEMA IF NOT EXISTS refined;

CREATE TABLE IF NOT EXISTS refined.dtc_codes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    code TEXT NOT NULL,
    description TEXT,
    category TEXT,
    severity TEXT,
    confidence_score FLOAT NOT NULL DEFAULT 0.5
        CHECK (confidence_score >= 0 AND confidence_score <= 1),
    source_count INT DEFAULT 1,
    first_seen TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(code)
);

CREATE INDEX IF NOT EXISTS idx_dtc_code
    ON refined.dtc_codes(code);

CREATE TABLE IF NOT EXISTS refined.dtc_sources (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    dtc_id UUID NOT NULL REFERENCES refined.dtc_codes(id) ON DELETE CASCADE,
    chunk_id UUID NOT NULL REFERENCES research.document_chunks(id) ON DELETE CASCADE,
    extracted_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(dtc_id, chunk_id)
);

CREATE TABLE IF NOT EXISTS refined.diagnostic_steps (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    dtc_id UUID REFERENCES refined.dtc_codes(id) ON DELETE SET NULL,
    step_order INT NOT NULL,
    description TEXT NOT NULL,
    tools_required TEXT,
    expected_values TEXT,
    source_chunk_id UUID REFERENCES research.document_chunks(id) ON DELETE SET NULL,
    confidence_score FLOAT DEFAULT 0.5,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_diag_steps_dtc
    ON refined.diagnostic_steps(dtc_id);

CREATE TABLE IF NOT EXISTS refined.causes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    dtc_id UUID REFERENCES refined.dtc_codes(id) ON DELETE SET NULL,
    description TEXT NOT NULL,
    likelihood TEXT,
    source_chunk_id UUID REFERENCES research.document_chunks(id) ON DELETE SET NULL,
    confidence_score FLOAT DEFAULT 0.5,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_causes_dtc
    ON refined.causes(dtc_id);

CREATE TABLE IF NOT EXISTS refined.sensors (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    sensor_type TEXT,
    typical_range TEXT,
    unit TEXT,
    related_dtc_codes TEXT[],
    source_chunk_id UUID REFERENCES research.document_chunks(id) ON DELETE SET NULL,
    confidence_score FLOAT DEFAULT 0.5,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(name, sensor_type)
);

CREATE TABLE IF NOT EXISTS refined.tsb_references (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tsb_number TEXT NOT NULL,
    title TEXT,
    affected_models TEXT,
    related_dtc_codes TEXT[],
    summary TEXT,
    source_chunk_id UUID REFERENCES research.document_chunks(id) ON DELETE SET NULL,
    confidence_score FLOAT DEFAULT 0.5,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(tsb_number)
);

-- ==========================================================
-- MONITORING & HEALING SCHEMA
-- ==========================================================

CREATE TABLE IF NOT EXISTS research.healing_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    alert_id TEXT,
    action_type TEXT NOT NULL,
    component TEXT,
    decision TEXT NOT NULL,
    success BOOLEAN,
    result TEXT,
    llm_reasoning TEXT,
    reason TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_healing_log_created
    ON research.healing_log(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_healing_log_component
    ON research.healing_log(component, created_at DESC);

-- ==========================================================
-- ORCHESTRATION SCHEMA (Autonomous Management Layer)
-- ==========================================================

-- Task management for orchestrator
CREATE TABLE IF NOT EXISTS research.orchestrator_tasks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    priority INT NOT NULL DEFAULT 5,
    payload JSONB DEFAULT '{}',
    result JSONB,
    assigned_to TEXT,
    error_message TEXT,
    retry_count INT DEFAULT 0,
    scheduled_after TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_orch_tasks_status
    ON research.orchestrator_tasks(status);
CREATE INDEX IF NOT EXISTS idx_orch_tasks_priority
    ON research.orchestrator_tasks(priority, created_at);
CREATE INDEX IF NOT EXISTS idx_orch_tasks_type
    ON research.orchestrator_tasks(task_type);

-- Orchestrator audit trail
CREATE TABLE IF NOT EXISTS research.orchestrator_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    cycle_number INT NOT NULL,
    action TEXT NOT NULL,
    details JSONB DEFAULT '{}',
    system_state JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_orch_log_cycle
    ON research.orchestrator_log(cycle_number DESC);
CREATE INDEX IF NOT EXISTS idx_orch_log_created
    ON research.orchestrator_log(created_at DESC);

-- Domain/source tracking for researcher
CREATE TABLE IF NOT EXISTS research.research_sources (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    domain TEXT NOT NULL,
    url_pattern TEXT,
    source_type TEXT DEFAULT 'template',
    quality_tier INT DEFAULT 3 CHECK (quality_tier >= 1 AND quality_tier <= 5),
    last_crawled_at TIMESTAMP WITH TIME ZONE,
    total_urls_crawled INT DEFAULT 0,
    avg_trust_score FLOAT DEFAULT 0.0,
    is_blocked BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(domain)
);

CREATE INDEX IF NOT EXISTS idx_research_sources_domain
    ON research.research_sources(domain);

-- Research planning
CREATE TABLE IF NOT EXISTS research.research_plans (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    plan_type TEXT NOT NULL,
    target_dtc_codes TEXT[],
    target_topic TEXT,
    priority INT DEFAULT 5,
    status TEXT NOT NULL DEFAULT 'pending',
    urls_submitted INT DEFAULT 0,
    urls_successful INT DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_research_plans_status
    ON research.research_plans(status);

-- Audit reports
CREATE TABLE IF NOT EXISTS research.audit_reports (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    report_type TEXT NOT NULL,
    summary TEXT,
    metrics JSONB DEFAULT '{}',
    recommendations JSONB DEFAULT '[]',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_reports_type
    ON research.audit_reports(report_type);
CREATE INDEX IF NOT EXISTS idx_audit_reports_created
    ON research.audit_reports(created_at DESC);

-- Coverage tracking snapshots
CREATE TABLE IF NOT EXISTS research.coverage_snapshots (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    snapshot_date DATE NOT NULL,
    total_dtc_codes INT DEFAULT 0,
    by_category JSONB DEFAULT '{}',
    by_confidence_tier JSONB DEFAULT '{}',
    gap_ranges JSONB DEFAULT '[]',
    completeness_score FLOAT DEFAULT 0.0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(snapshot_date)
);

CREATE INDEX IF NOT EXISTS idx_coverage_date
    ON research.coverage_snapshots(snapshot_date DESC);
