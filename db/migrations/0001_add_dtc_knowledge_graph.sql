-- ==========================================================
-- Migration 0001: DTC Knowledge Graph Schema
-- ==========================================================
-- Creates the normalized knowledge graph for DTC codes,
-- symptoms, causes, verified fixes, parts, sensors,
-- forum threads, TSBs, recalls, and diagnostic trees.
--
-- All tables use UUID primary keys via uuid_generate_v4().
-- Depends on: research.document_chunks, vehicle.vehicles
-- ==========================================================

CREATE SCHEMA IF NOT EXISTS knowledge;

-- ----------------------------------------------------------
-- 1. REFERENCE / DIMENSION TABLES
-- ----------------------------------------------------------

-- Canonical make list (Ford, Toyota, etc.)
CREATE TABLE IF NOT EXISTS knowledge.makes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT uq_makes_name UNIQUE (name)
);

-- Model per make (F-150, Camry, etc.)
CREATE TABLE IF NOT EXISTS knowledge.models (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    make_id UUID NOT NULL REFERENCES knowledge.makes(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT uq_models_make_name UNIQUE (make_id, name)
);

CREATE INDEX IF NOT EXISTS idx_models_make_id
    ON knowledge.models(make_id);

-- Parts catalog (generic parts referenced by DTC fixes)
CREATE TABLE IF NOT EXISTS knowledge.parts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    part_number TEXT,
    category TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT uq_parts_name_number UNIQUE (name, COALESCE(part_number, ''))
);

CREATE INDEX IF NOT EXISTS idx_parts_category
    ON knowledge.parts(category);

-- Sensor type taxonomy (O2, MAP, MAF, etc.)
CREATE TABLE IF NOT EXISTS knowledge.sensor_types (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT uq_sensor_types_name UNIQUE (name)
);

-- Knowledge-layer sensors (separate from refined.sensors / vehicle.sensors)
CREATE TABLE IF NOT EXISTS knowledge.sensors (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    sensor_type_id UUID REFERENCES knowledge.sensor_types(id) ON DELETE SET NULL,
    manufacturer TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT uq_sensors_name_mfr UNIQUE (name, COALESCE(manufacturer, ''))
);

CREATE INDEX IF NOT EXISTS idx_kg_sensors_type_id
    ON knowledge.sensors(sensor_type_id);

-- Forum category taxonomy
CREATE TABLE IF NOT EXISTS knowledge.forum_categories (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    platform TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT uq_forum_categories_name UNIQUE (name)
);

-- Forum threads harvested from community sources
CREATE TABLE IF NOT EXISTS knowledge.forum_threads (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    category_id UUID REFERENCES knowledge.forum_categories(id) ON DELETE SET NULL,
    platform TEXT,
    external_url TEXT,
    title TEXT,
    author TEXT,
    post_date TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_forum_threads_category_id
    ON knowledge.forum_threads(category_id);
CREATE INDEX IF NOT EXISTS idx_forum_threads_platform
    ON knowledge.forum_threads(platform);

-- Technical Service Bulletins (manufacturer-issued)
CREATE TABLE IF NOT EXISTS knowledge.tsb (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tsb_number TEXT NOT NULL,
    title TEXT,
    description TEXT,
    issue_date DATE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT uq_tsb_number UNIQUE (tsb_number)
);

CREATE INDEX IF NOT EXISTS idx_tsb_issue_date
    ON knowledge.tsb(issue_date);

-- Safety recalls
CREATE TABLE IF NOT EXISTS knowledge.recalls (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    recall_number TEXT NOT NULL,
    title TEXT,
    description TEXT,
    issue_date DATE,
    affected_components TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT uq_recall_number UNIQUE (recall_number)
);

CREATE INDEX IF NOT EXISTS idx_recalls_issue_date
    ON knowledge.recalls(issue_date);

-- ----------------------------------------------------------
-- 2. DTC MASTER - Core fact table
-- ----------------------------------------------------------

CREATE TABLE IF NOT EXISTS knowledge.dtc_master (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    code TEXT NOT NULL,
    system_category TEXT,            -- e.g. 'Powertrain', 'Body', 'Chassis'
    subsystem TEXT,                  -- e.g. 'Fuel System', 'Ignition'
    generic_description TEXT,
    severity_level INT CHECK (severity_level >= 1 AND severity_level <= 5),
    driveability_impact BOOLEAN DEFAULT FALSE,
    emissions_related BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT uq_dtc_master_code UNIQUE (code)
);

COMMENT ON TABLE knowledge.dtc_master IS 'Canonical DTC definitions - one row per unique code (e.g. P0301)';

CREATE INDEX IF NOT EXISTS idx_dtc_master_code
    ON knowledge.dtc_master(code);
CREATE INDEX IF NOT EXISTS idx_dtc_master_system_category
    ON knowledge.dtc_master(system_category);
CREATE INDEX IF NOT EXISTS idx_dtc_master_severity
    ON knowledge.dtc_master(severity_level);

-- ----------------------------------------------------------
-- 3. DTC DETAIL / RELATIONSHIP TABLES
-- ----------------------------------------------------------

-- OEM-specific variant descriptions per make/model/year range
CREATE TABLE IF NOT EXISTS knowledge.dtc_oem_variant (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    dtc_master_id UUID NOT NULL REFERENCES knowledge.dtc_master(id) ON DELETE CASCADE,
    make_id UUID NOT NULL REFERENCES knowledge.makes(id) ON DELETE CASCADE,
    model_id UUID REFERENCES knowledge.models(id) ON DELETE SET NULL,
    year_start INT,
    year_end INT,
    oem_description TEXT,
    tsb_reference TEXT,
    known_pattern_failure BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT uq_dtc_oem_variant UNIQUE (
        dtc_master_id,
        make_id,
        COALESCE(model_id, '00000000-0000-0000-0000-000000000000'::uuid),
        COALESCE(year_start, 0),
        COALESCE(year_end, 0)
    )
);

CREATE INDEX IF NOT EXISTS idx_dtc_oem_variant_dtc
    ON knowledge.dtc_oem_variant(dtc_master_id);
CREATE INDEX IF NOT EXISTS idx_dtc_oem_variant_make
    ON knowledge.dtc_oem_variant(make_id);
CREATE INDEX IF NOT EXISTS idx_dtc_oem_variant_model
    ON knowledge.dtc_oem_variant(model_id);
CREATE INDEX IF NOT EXISTS idx_dtc_oem_variant_years
    ON knowledge.dtc_oem_variant(year_start, year_end);

-- Symptoms associated with a DTC
CREATE TABLE IF NOT EXISTS knowledge.dtc_symptoms (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    dtc_master_id UUID NOT NULL REFERENCES knowledge.dtc_master(id) ON DELETE CASCADE,
    symptom TEXT NOT NULL,
    frequency_score INT DEFAULT 5 CHECK (frequency_score >= 1 AND frequency_score <= 10),
    evidence_count INT DEFAULT 0,
    avg_trust FLOAT DEFAULT 0 CHECK (avg_trust >= 0 AND avg_trust <= 1),
    avg_relevance FLOAT DEFAULT 0 CHECK (avg_relevance >= 0 AND avg_relevance <= 1),
    conflict_flag BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT uq_dtc_symptoms UNIQUE (dtc_master_id, lower(symptom))
);

COMMENT ON TABLE knowledge.dtc_symptoms IS 'Crowd/AI-sourced symptoms per DTC with trust metrics';

CREATE INDEX IF NOT EXISTS idx_dtc_symptoms_dtc
    ON knowledge.dtc_symptoms(dtc_master_id);
CREATE INDEX IF NOT EXISTS idx_dtc_symptoms_conflict
    ON knowledge.dtc_symptoms(conflict_flag) WHERE conflict_flag = TRUE;

-- Possible causes for a DTC
CREATE TABLE IF NOT EXISTS knowledge.dtc_possible_causes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    dtc_master_id UUID NOT NULL REFERENCES knowledge.dtc_master(id) ON DELETE CASCADE,
    cause TEXT NOT NULL,
    probability_weight FLOAT DEFAULT 0.5 CHECK (probability_weight >= 0 AND probability_weight <= 1),
    evidence_count INT DEFAULT 0,
    avg_trust FLOAT DEFAULT 0 CHECK (avg_trust >= 0 AND avg_trust <= 1),
    avg_relevance FLOAT DEFAULT 0 CHECK (avg_relevance >= 0 AND avg_relevance <= 1),
    conflict_flag BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT uq_dtc_causes UNIQUE (dtc_master_id, lower(cause))
);

COMMENT ON TABLE knowledge.dtc_possible_causes IS 'Ranked possible causes per DTC with probability weights';

CREATE INDEX IF NOT EXISTS idx_dtc_causes_dtc
    ON knowledge.dtc_possible_causes(dtc_master_id);
CREATE INDEX IF NOT EXISTS idx_dtc_causes_probability
    ON knowledge.dtc_possible_causes(dtc_master_id, probability_weight DESC);
CREATE INDEX IF NOT EXISTS idx_dtc_causes_conflict
    ON knowledge.dtc_possible_causes(conflict_flag) WHERE conflict_flag = TRUE;

-- Verified fixes with cost/labor estimates
CREATE TABLE IF NOT EXISTS knowledge.dtc_verified_fixes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    dtc_master_id UUID NOT NULL REFERENCES knowledge.dtc_master(id) ON DELETE CASCADE,
    make_id UUID REFERENCES knowledge.makes(id) ON DELETE SET NULL,
    model_id UUID REFERENCES knowledge.models(id) ON DELETE SET NULL,
    engine_code TEXT,
    fix_description TEXT NOT NULL,
    confirmed_repair_count INT DEFAULT 0,
    average_cost NUMERIC(10, 2),
    average_labor_hours NUMERIC(5, 2),
    evidence_count INT DEFAULT 0,
    avg_trust FLOAT DEFAULT 0 CHECK (avg_trust >= 0 AND avg_trust <= 1),
    avg_relevance FLOAT DEFAULT 0 CHECK (avg_relevance >= 0 AND avg_relevance <= 1),
    conflict_flag BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

COMMENT ON TABLE knowledge.dtc_verified_fixes IS 'Community/OEM-verified repairs per DTC, optionally scoped to make/model/engine';

CREATE INDEX IF NOT EXISTS idx_dtc_fixes_dtc
    ON knowledge.dtc_verified_fixes(dtc_master_id);
CREATE INDEX IF NOT EXISTS idx_dtc_fixes_make
    ON knowledge.dtc_verified_fixes(make_id);
CREATE INDEX IF NOT EXISTS idx_dtc_fixes_model
    ON knowledge.dtc_verified_fixes(model_id);
CREATE INDEX IF NOT EXISTS idx_dtc_fixes_engine
    ON knowledge.dtc_verified_fixes(engine_code);
CREATE INDEX IF NOT EXISTS idx_dtc_fixes_confirmed
    ON knowledge.dtc_verified_fixes(dtc_master_id, confirmed_repair_count DESC);

-- Parts commonly related to a DTC
CREATE TABLE IF NOT EXISTS knowledge.dtc_related_parts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    dtc_master_id UUID NOT NULL REFERENCES knowledge.dtc_master(id) ON DELETE CASCADE,
    part_category TEXT,
    part_id UUID NOT NULL REFERENCES knowledge.parts(id) ON DELETE CASCADE,
    priority_rank INT,
    evidence_count INT DEFAULT 0,
    avg_trust FLOAT DEFAULT 0 CHECK (avg_trust >= 0 AND avg_trust <= 1),
    avg_relevance FLOAT DEFAULT 0 CHECK (avg_relevance >= 0 AND avg_relevance <= 1),
    conflict_flag BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT uq_dtc_related_parts UNIQUE (dtc_master_id, part_id)
);

CREATE INDEX IF NOT EXISTS idx_dtc_parts_dtc
    ON knowledge.dtc_related_parts(dtc_master_id);
CREATE INDEX IF NOT EXISTS idx_dtc_parts_part
    ON knowledge.dtc_related_parts(part_id);
CREATE INDEX IF NOT EXISTS idx_dtc_parts_rank
    ON knowledge.dtc_related_parts(dtc_master_id, priority_rank);

-- Sensors commonly related to a DTC
CREATE TABLE IF NOT EXISTS knowledge.dtc_related_sensors (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    dtc_master_id UUID NOT NULL REFERENCES knowledge.dtc_master(id) ON DELETE CASCADE,
    sensor_id UUID NOT NULL REFERENCES knowledge.sensors(id) ON DELETE CASCADE,
    priority_rank INT,
    evidence_count INT DEFAULT 0,
    avg_trust FLOAT DEFAULT 0 CHECK (avg_trust >= 0 AND avg_trust <= 1),
    avg_relevance FLOAT DEFAULT 0 CHECK (avg_relevance >= 0 AND avg_relevance <= 1),
    conflict_flag BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT uq_dtc_related_sensors UNIQUE (dtc_master_id, sensor_id)
);

CREATE INDEX IF NOT EXISTS idx_dtc_sensors_dtc
    ON knowledge.dtc_related_sensors(dtc_master_id);
CREATE INDEX IF NOT EXISTS idx_dtc_sensors_sensor
    ON knowledge.dtc_related_sensors(sensor_id);
CREATE INDEX IF NOT EXISTS idx_dtc_sensors_rank
    ON knowledge.dtc_related_sensors(dtc_master_id, priority_rank);

-- OBD-II live data parameters relevant to a DTC
CREATE TABLE IF NOT EXISTS knowledge.dtc_live_data_parameters (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    dtc_master_id UUID NOT NULL REFERENCES knowledge.dtc_master(id) ON DELETE CASCADE,
    pid_name TEXT NOT NULL,
    normal_range_min FLOAT,
    normal_range_max FLOAT,
    unit TEXT,
    evidence_count INT DEFAULT 0,
    avg_trust FLOAT DEFAULT 0 CHECK (avg_trust >= 0 AND avg_trust <= 1),
    avg_relevance FLOAT DEFAULT 0 CHECK (avg_relevance >= 0 AND avg_relevance <= 1),
    conflict_flag BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT uq_dtc_live_data UNIQUE (dtc_master_id, pid_name)
);

CREATE INDEX IF NOT EXISTS idx_dtc_live_data_dtc
    ON knowledge.dtc_live_data_parameters(dtc_master_id);

-- AI-generated plain-language explanations per DTC
CREATE TABLE IF NOT EXISTS knowledge.dtc_ai_explanations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    dtc_master_id UUID NOT NULL REFERENCES knowledge.dtc_master(id) ON DELETE CASCADE,
    explanation_simple TEXT,       -- consumer-friendly
    explanation_advanced TEXT,     -- technician-level
    diagnostic_strategy TEXT,     -- step-by-step reasoning
    confidence_score FLOAT DEFAULT 0.5 CHECK (confidence_score >= 0 AND confidence_score <= 1),
    model_used TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT uq_dtc_ai_explanation UNIQUE (dtc_master_id)
);

CREATE INDEX IF NOT EXISTS idx_dtc_ai_expl_dtc
    ON knowledge.dtc_ai_explanations(dtc_master_id);

-- ----------------------------------------------------------
-- 4. VEHICLE / OCCURRENCE TABLES
-- ----------------------------------------------------------

-- Tracks actual DTC occurrences on specific vehicles
CREATE TABLE IF NOT EXISTS knowledge.vehicle_dtc_occurrence (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    vehicle_id UUID NOT NULL REFERENCES vehicle.vehicles(id) ON DELETE CASCADE,
    dtc_master_id UUID NOT NULL REFERENCES knowledge.dtc_master(id) ON DELETE CASCADE,
    mileage INT,
    freeze_frame JSONB DEFAULT '{}',
    first_seen TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_seen TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    resolved BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

COMMENT ON TABLE knowledge.vehicle_dtc_occurrence IS 'Actual DTC events on real vehicles with freeze-frame data';

CREATE INDEX IF NOT EXISTS idx_veh_dtc_occ_vehicle
    ON knowledge.vehicle_dtc_occurrence(vehicle_id);
CREATE INDEX IF NOT EXISTS idx_veh_dtc_occ_dtc
    ON knowledge.vehicle_dtc_occurrence(dtc_master_id);
CREATE INDEX IF NOT EXISTS idx_veh_dtc_occ_vehicle_dtc
    ON knowledge.vehicle_dtc_occurrence(vehicle_id, dtc_master_id);
CREATE INDEX IF NOT EXISTS idx_veh_dtc_occ_resolved
    ON knowledge.vehicle_dtc_occurrence(resolved) WHERE resolved = FALSE;

-- ----------------------------------------------------------
-- 5. FORUM THREAD LINKAGE
-- ----------------------------------------------------------

-- Links DTCs to relevant forum threads for evidence
CREATE TABLE IF NOT EXISTS knowledge.dtc_forum_threads (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    dtc_master_id UUID NOT NULL REFERENCES knowledge.dtc_master(id) ON DELETE CASCADE,
    vehicle_id UUID REFERENCES vehicle.vehicles(id) ON DELETE SET NULL,
    thread_id UUID NOT NULL REFERENCES knowledge.forum_threads(id) ON DELETE CASCADE,
    solution_marked BOOLEAN DEFAULT FALSE,
    evidence_count INT DEFAULT 0,
    avg_trust FLOAT DEFAULT 0 CHECK (avg_trust >= 0 AND avg_trust <= 1),
    avg_relevance FLOAT DEFAULT 0 CHECK (avg_relevance >= 0 AND avg_relevance <= 1),
    conflict_flag BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT uq_dtc_forum_threads UNIQUE (dtc_master_id, thread_id)
);

CREATE INDEX IF NOT EXISTS idx_dtc_forum_dtc
    ON knowledge.dtc_forum_threads(dtc_master_id);
CREATE INDEX IF NOT EXISTS idx_dtc_forum_thread
    ON knowledge.dtc_forum_threads(thread_id);
CREATE INDEX IF NOT EXISTS idx_dtc_forum_vehicle
    ON knowledge.dtc_forum_threads(vehicle_id);
CREATE INDEX IF NOT EXISTS idx_dtc_forum_solution
    ON knowledge.dtc_forum_threads(solution_marked) WHERE solution_marked = TRUE;

-- ----------------------------------------------------------
-- 6. DIAGNOSTIC DECISION TREE
-- ----------------------------------------------------------

-- Ordered diagnostic steps with pass/fail branching
CREATE TABLE IF NOT EXISTS knowledge.dtc_diagnostic_steps (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    dtc_master_id UUID NOT NULL REFERENCES knowledge.dtc_master(id) ON DELETE CASCADE,
    step_order INT NOT NULL,
    instruction TEXT NOT NULL,
    pass_next_step_id UUID REFERENCES knowledge.dtc_diagnostic_steps(id) ON DELETE SET NULL,
    fail_next_step_id UUID REFERENCES knowledge.dtc_diagnostic_steps(id) ON DELETE SET NULL,
    terminal_outcome_flag BOOLEAN DEFAULT FALSE,
    evidence_count INT DEFAULT 0,
    avg_trust FLOAT DEFAULT 0 CHECK (avg_trust >= 0 AND avg_trust <= 1),
    avg_relevance FLOAT DEFAULT 0 CHECK (avg_relevance >= 0 AND avg_relevance <= 1),
    conflict_flag BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

COMMENT ON TABLE knowledge.dtc_diagnostic_steps IS 'Diagnostic decision tree - each step branches on pass/fail to next step or terminal outcome';

CREATE INDEX IF NOT EXISTS idx_dtc_diag_steps_dtc
    ON knowledge.dtc_diagnostic_steps(dtc_master_id);
CREATE INDEX IF NOT EXISTS idx_dtc_diag_steps_order
    ON knowledge.dtc_diagnostic_steps(dtc_master_id, step_order);
CREATE INDEX IF NOT EXISTS idx_dtc_diag_steps_pass
    ON knowledge.dtc_diagnostic_steps(pass_next_step_id);
CREATE INDEX IF NOT EXISTS idx_dtc_diag_steps_fail
    ON knowledge.dtc_diagnostic_steps(fail_next_step_id);
