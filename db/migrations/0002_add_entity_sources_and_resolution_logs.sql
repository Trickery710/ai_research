-- ==========================================================
-- Migration 0002: Entity Source Provenance & Resolution Logs
-- ==========================================================
-- Adds provenance tracking (which chunk sourced each entity)
-- and an audit log for merge/reject/create/update decisions
-- made during knowledge graph resolution runs.
--
-- Depends on: 0001_add_dtc_knowledge_graph.sql
--             research.document_chunks (init.sql)
-- ==========================================================

-- ----------------------------------------------------------
-- 1. ENTITY SOURCE PROVENANCE
-- ----------------------------------------------------------
-- Tracks which research.document_chunks chunk contributed to
-- each entity row in any knowledge.* table. Enables full
-- lineage from raw document -> chunk -> knowledge entity.

CREATE TABLE IF NOT EXISTS knowledge.dtc_entity_sources (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_table TEXT NOT NULL,          -- e.g. 'knowledge.dtc_symptoms'
    entity_id UUID NOT NULL,             -- PK of the row in that table
    chunk_id UUID NOT NULL REFERENCES research.document_chunks(id) ON DELETE CASCADE,
    trust_score FLOAT CHECK (trust_score IS NULL OR (trust_score >= 0 AND trust_score <= 1)),
    relevance_score FLOAT CHECK (relevance_score IS NULL OR (relevance_score >= 0 AND relevance_score <= 1)),
    extracted_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

COMMENT ON TABLE knowledge.dtc_entity_sources IS
    'Provenance: links every knowledge entity back to the document chunk it was extracted from';

CREATE INDEX IF NOT EXISTS idx_entity_sources_table_entity
    ON knowledge.dtc_entity_sources(entity_table, entity_id);

CREATE INDEX IF NOT EXISTS idx_entity_sources_chunk
    ON knowledge.dtc_entity_sources(chunk_id);

CREATE INDEX IF NOT EXISTS idx_entity_sources_scores
    ON knowledge.dtc_entity_sources(trust_score, relevance_score);

-- ----------------------------------------------------------
-- 2. RESOLUTION LOG (audit trail)
-- ----------------------------------------------------------
-- Records every action taken during a knowledge-graph
-- resolution run: merges, rejections, creates, updates.
-- Grouped by run_id so each batch is traceable.

CREATE TABLE IF NOT EXISTS knowledge.resolution_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    dtc_master_id UUID REFERENCES knowledge.dtc_master(id) ON DELETE SET NULL,
    run_id UUID NOT NULL,                -- groups actions from a single resolution batch
    action TEXT NOT NULL                  -- 'merged', 'rejected', 'created', 'updated'
        CHECK (action IN ('merged', 'rejected', 'created', 'updated')),
    entity_table TEXT,                   -- which table was affected
    entity_id UUID,                      -- which row was affected
    details JSONB DEFAULT '{}',          -- free-form context (old values, reasoning, etc.)
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

COMMENT ON TABLE knowledge.resolution_log IS
    'Audit trail for all knowledge-graph resolution actions, grouped by run_id';

CREATE INDEX IF NOT EXISTS idx_resolution_log_dtc_run
    ON knowledge.resolution_log(dtc_master_id, run_id);

CREATE INDEX IF NOT EXISTS idx_resolution_log_run
    ON knowledge.resolution_log(run_id);

CREATE INDEX IF NOT EXISTS idx_resolution_log_action
    ON knowledge.resolution_log(action);

CREATE INDEX IF NOT EXISTS idx_resolution_log_created
    ON knowledge.resolution_log(created_at);
