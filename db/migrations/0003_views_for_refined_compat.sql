-- ==========================================================
-- Migration 0003: Compatibility Views (knowledge -> refined)
-- ==========================================================
-- Creates views in the refined schema that map the new
-- knowledge.* tables back to the old refined.* table
-- structure. This lets existing API queries continue to
-- work against refined.v_dtc_codes, refined.v_causes,
-- and refined.v_diagnostic_steps without modification.
--
-- IMPORTANT: The original refined tables are NOT dropped.
-- These are additive read-only views only.
--
-- Depends on: 0001_add_dtc_knowledge_graph.sql
-- ==========================================================

-- ----------------------------------------------------------
-- 1. refined.v_dtc_codes
-- ----------------------------------------------------------
-- Maps knowledge.dtc_master -> refined.dtc_codes shape.
--
-- Column mapping:
--   id              -> dtc_master.id
--   code            -> dtc_master.code
--   description     -> dtc_master.generic_description
--   category        -> dtc_master.system_category
--   severity        -> cast severity_level to text
--   confidence_score -> dtc_ai_explanations.confidence_score (fallback 0.5)
--   source_count    -> count of entity sources for this DTC
--   first_seen      -> dtc_master.created_at
--   updated_at      -> dtc_master.updated_at
--   verified_at     -> NULL (not tracked in knowledge schema yet)
--   verification_status -> 'unverified'
--   verification_model  -> NULL
--   pre_verification_confidence -> NULL

CREATE OR REPLACE VIEW refined.v_dtc_codes AS
SELECT
    dm.id,
    dm.code,
    dm.generic_description                          AS description,
    dm.system_category                              AS category,
    CASE dm.severity_level
        WHEN 1 THEN 'info'
        WHEN 2 THEN 'low'
        WHEN 3 THEN 'medium'
        WHEN 4 THEN 'high'
        WHEN 5 THEN 'critical'
        ELSE NULL
    END                                             AS severity,
    COALESCE(ae.confidence_score, 0.5)              AS confidence_score,
    COALESCE(src_counts.source_count, 0)::INT       AS source_count,
    dm.created_at                                   AS first_seen,
    dm.updated_at,
    NULL::TIMESTAMP WITH TIME ZONE                  AS verified_at,
    'unverified'::TEXT                              AS verification_status,
    NULL::TEXT                                       AS verification_model,
    NULL::FLOAT                                     AS pre_verification_confidence
FROM knowledge.dtc_master dm
LEFT JOIN knowledge.dtc_ai_explanations ae
    ON ae.dtc_master_id = dm.id
LEFT JOIN (
    SELECT
        entity_id,
        COUNT(*) AS source_count
    FROM knowledge.dtc_entity_sources
    WHERE entity_table = 'knowledge.dtc_master'
    GROUP BY entity_id
) src_counts
    ON src_counts.entity_id = dm.id;

COMMENT ON VIEW refined.v_dtc_codes IS
    'Compatibility view: reads from knowledge.dtc_master, shaped like refined.dtc_codes';

-- ----------------------------------------------------------
-- 2. refined.v_causes
-- ----------------------------------------------------------
-- Maps knowledge.dtc_possible_causes -> refined.causes shape.
--
-- Column mapping:
--   id              -> dtc_possible_causes.id
--   dtc_id          -> dtc_possible_causes.dtc_master_id
--   description     -> dtc_possible_causes.cause
--   likelihood      -> derived from probability_weight
--   source_chunk_id -> first chunk from entity_sources (nullable)
--   confidence_score -> probability_weight
--   created_at      -> dtc_possible_causes.created_at

CREATE OR REPLACE VIEW refined.v_causes AS
SELECT
    pc.id,
    pc.dtc_master_id                                AS dtc_id,
    pc.cause                                        AS description,
    CASE
        WHEN pc.probability_weight >= 0.8 THEN 'very likely'
        WHEN pc.probability_weight >= 0.6 THEN 'likely'
        WHEN pc.probability_weight >= 0.4 THEN 'possible'
        WHEN pc.probability_weight >= 0.2 THEN 'unlikely'
        ELSE 'rare'
    END                                             AS likelihood,
    first_src.chunk_id                              AS source_chunk_id,
    pc.probability_weight                           AS confidence_score,
    pc.created_at
FROM knowledge.dtc_possible_causes pc
LEFT JOIN LATERAL (
    SELECT es.chunk_id
    FROM knowledge.dtc_entity_sources es
    WHERE es.entity_table = 'knowledge.dtc_possible_causes'
      AND es.entity_id = pc.id
    ORDER BY es.extracted_at
    LIMIT 1
) first_src ON TRUE;

COMMENT ON VIEW refined.v_causes IS
    'Compatibility view: reads from knowledge.dtc_possible_causes, shaped like refined.causes';

-- ----------------------------------------------------------
-- 3. refined.v_diagnostic_steps
-- ----------------------------------------------------------
-- Maps knowledge.dtc_diagnostic_steps -> refined.diagnostic_steps shape.
--
-- Column mapping:
--   id              -> dtc_diagnostic_steps.id
--   dtc_id          -> dtc_diagnostic_steps.dtc_master_id
--   step_order      -> dtc_diagnostic_steps.step_order
--   description     -> dtc_diagnostic_steps.instruction
--   tools_required  -> NULL (not in knowledge schema)
--   expected_values -> NULL (not in knowledge schema)
--   source_chunk_id -> first chunk from entity_sources (nullable)
--   confidence_score -> avg_trust (maps closest to the original meaning)
--   created_at      -> dtc_diagnostic_steps.created_at

CREATE OR REPLACE VIEW refined.v_diagnostic_steps AS
SELECT
    ds.id,
    ds.dtc_master_id                                AS dtc_id,
    ds.step_order,
    ds.instruction                                  AS description,
    NULL::TEXT                                       AS tools_required,
    NULL::TEXT                                       AS expected_values,
    first_src.chunk_id                              AS source_chunk_id,
    ds.avg_trust                                    AS confidence_score,
    ds.created_at
FROM knowledge.dtc_diagnostic_steps ds
LEFT JOIN LATERAL (
    SELECT es.chunk_id
    FROM knowledge.dtc_entity_sources es
    WHERE es.entity_table = 'knowledge.dtc_diagnostic_steps'
      AND es.entity_id = ds.id
    ORDER BY es.extracted_at
    LIMIT 1
) first_src ON TRUE;

COMMENT ON VIEW refined.v_diagnostic_steps IS
    'Compatibility view: reads from knowledge.dtc_diagnostic_steps, shaped like refined.diagnostic_steps';
