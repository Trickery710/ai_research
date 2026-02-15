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

-- ==========================================================
-- VEHICLE SCHEMA (Automotive Reference Data Layer)
-- ==========================================================
CREATE SCHEMA IF NOT EXISTS vehicle;

-- ----------------------------------------------------------
-- 1. VEHICLE IDENTIFICATION
-- ----------------------------------------------------------

-- Core vehicle definition: year/make/model/generation/trim
CREATE TABLE IF NOT EXISTS vehicle.vehicles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    year INT NOT NULL CHECK (year >= 1886 AND year <= 2100),
    make TEXT NOT NULL,
    model TEXT NOT NULL,
    generation TEXT,
    trim TEXT,
    body_style TEXT,
    drive_type TEXT,
    production_start DATE,
    production_end DATE,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_vehicles_unique
    ON vehicle.vehicles(year, make, model, COALESCE(generation, ''), COALESCE(trim, ''));
CREATE INDEX IF NOT EXISTS idx_vehicles_make_model
    ON vehicle.vehicles(make, model);
CREATE INDEX IF NOT EXISTS idx_vehicles_year
    ON vehicle.vehicles(year);
CREATE INDEX IF NOT EXISTS idx_vehicles_make_model_year
    ON vehicle.vehicles(make, model, year);

-- Equipment / options catalog
CREATE TABLE IF NOT EXISTS vehicle.equipment_options (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    description TEXT,
    option_code TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_equipment_unique
    ON vehicle.equipment_options(name, COALESCE(option_code, ''));

CREATE INDEX IF NOT EXISTS idx_equipment_category
    ON vehicle.equipment_options(category);

-- Junction: vehicle <-> equipment
CREATE TABLE IF NOT EXISTS vehicle.vehicle_equipment (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    vehicle_id UUID NOT NULL REFERENCES vehicle.vehicles(id) ON DELETE CASCADE,
    equipment_id UUID NOT NULL REFERENCES vehicle.equipment_options(id) ON DELETE CASCADE,
    is_standard BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(vehicle_id, equipment_id)
);

CREATE INDEX IF NOT EXISTS idx_vehicle_equipment_vehicle
    ON vehicle.vehicle_equipment(vehicle_id);
CREATE INDEX IF NOT EXISTS idx_vehicle_equipment_equipment
    ON vehicle.vehicle_equipment(equipment_id);

-- VIN position definitions (what each position range encodes)
CREATE TABLE IF NOT EXISTS vehicle.vin_positions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    position_start INT NOT NULL CHECK (position_start >= 1 AND position_start <= 17),
    position_end INT NOT NULL CHECK (position_end >= 1 AND position_end <= 17),
    field_name TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(position_start, position_end, field_name),
    CHECK (position_end >= position_start)
);

-- VIN decode values (character(s) at positions -> meaning)
CREATE TABLE IF NOT EXISTS vehicle.vin_decode_values (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    position_def_id UUID NOT NULL REFERENCES vehicle.vin_positions(id) ON DELETE CASCADE,
    vin_characters TEXT NOT NULL,
    decoded_value TEXT NOT NULL,
    make TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_vin_decode_unique
    ON vehicle.vin_decode_values(position_def_id, vin_characters, COALESCE(make, ''));

CREATE INDEX IF NOT EXISTS idx_vin_decode_position
    ON vehicle.vin_decode_values(position_def_id);
CREATE INDEX IF NOT EXISTS idx_vin_decode_chars
    ON vehicle.vin_decode_values(vin_characters);
CREATE INDEX IF NOT EXISTS idx_vin_decode_make
    ON vehicle.vin_decode_values(make);

-- ----------------------------------------------------------
-- 2. POWERTRAIN
-- ----------------------------------------------------------

CREATE TABLE IF NOT EXISTS vehicle.engines (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    engine_code TEXT NOT NULL,
    displacement_liters FLOAT,
    fuel_type TEXT,
    cylinders INT,
    configuration TEXT,
    aspiration TEXT DEFAULT 'natural',
    horsepower INT,
    torque_ft_lbs INT,
    manufacturer TEXT,
    vin_identifier TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(engine_code)
);

CREATE INDEX IF NOT EXISTS idx_engines_code
    ON vehicle.engines(engine_code);
CREATE INDEX IF NOT EXISTS idx_engines_fuel_type
    ON vehicle.engines(fuel_type);

CREATE TABLE IF NOT EXISTS vehicle.transmissions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    transmission_code TEXT NOT NULL,
    transmission_type TEXT NOT NULL,
    speeds INT,
    manufacturer TEXT,
    vin_identifier TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(transmission_code)
);

CREATE INDEX IF NOT EXISTS idx_transmissions_code
    ON vehicle.transmissions(transmission_code);
CREATE INDEX IF NOT EXISTS idx_transmissions_type
    ON vehicle.transmissions(transmission_type);

-- Junction: vehicle <-> engine (many-to-many)
CREATE TABLE IF NOT EXISTS vehicle.vehicle_engines (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    vehicle_id UUID NOT NULL REFERENCES vehicle.vehicles(id) ON DELETE CASCADE,
    engine_id UUID NOT NULL REFERENCES vehicle.engines(id) ON DELETE CASCADE,
    is_standard BOOLEAN DEFAULT TRUE,
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(vehicle_id, engine_id)
);

CREATE INDEX IF NOT EXISTS idx_vehicle_engines_vehicle
    ON vehicle.vehicle_engines(vehicle_id);
CREATE INDEX IF NOT EXISTS idx_vehicle_engines_engine
    ON vehicle.vehicle_engines(engine_id);

-- Junction: vehicle <-> transmission (many-to-many)
CREATE TABLE IF NOT EXISTS vehicle.vehicle_transmissions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    vehicle_id UUID NOT NULL REFERENCES vehicle.vehicles(id) ON DELETE CASCADE,
    transmission_id UUID NOT NULL REFERENCES vehicle.transmissions(id) ON DELETE CASCADE,
    is_standard BOOLEAN DEFAULT TRUE,
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(vehicle_id, transmission_id)
);

CREATE INDEX IF NOT EXISTS idx_vehicle_trans_vehicle
    ON vehicle.vehicle_transmissions(vehicle_id);
CREATE INDEX IF NOT EXISTS idx_vehicle_trans_transmission
    ON vehicle.vehicle_transmissions(transmission_id);

-- ----------------------------------------------------------
-- 3. SENSOR CATALOG
-- ----------------------------------------------------------

-- Sensor manufacturers
CREATE TABLE IF NOT EXISTS vehicle.sensor_manufacturers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    country TEXT,
    website TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(name)
);

-- Sensor part numbers: per manufacturer, OEM vs aftermarket
CREATE TABLE IF NOT EXISTS vehicle.sensor_part_numbers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    sensor_id UUID NOT NULL REFERENCES refined.sensors(id) ON DELETE CASCADE,
    manufacturer_id UUID NOT NULL REFERENCES vehicle.sensor_manufacturers(id) ON DELETE CASCADE,
    part_number TEXT NOT NULL,
    is_oem BOOLEAN DEFAULT FALSE,
    price_usd NUMERIC(10,2),
    superseded_by UUID REFERENCES vehicle.sensor_part_numbers(id) ON DELETE SET NULL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(manufacturer_id, part_number)
);

CREATE INDEX IF NOT EXISTS idx_sensor_parts_sensor
    ON vehicle.sensor_part_numbers(sensor_id);
CREATE INDEX IF NOT EXISTS idx_sensor_parts_manufacturer
    ON vehicle.sensor_part_numbers(manufacturer_id);
CREATE INDEX IF NOT EXISTS idx_sensor_parts_part_number
    ON vehicle.sensor_part_numbers(part_number);
CREATE INDEX IF NOT EXISTS idx_sensor_parts_oem
    ON vehicle.sensor_part_numbers(is_oem);

-- Junction: vehicle <-> sensor with location
CREATE TABLE IF NOT EXISTS vehicle.vehicle_sensors (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    vehicle_id UUID NOT NULL REFERENCES vehicle.vehicles(id) ON DELETE CASCADE,
    sensor_id UUID NOT NULL REFERENCES refined.sensors(id) ON DELETE CASCADE,
    location TEXT,
    quantity INT DEFAULT 1,
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_vehicle_sensors_unique
    ON vehicle.vehicle_sensors(vehicle_id, sensor_id, COALESCE(location, ''));

CREATE INDEX IF NOT EXISTS idx_vehicle_sensors_vehicle
    ON vehicle.vehicle_sensors(vehicle_id);
CREATE INDEX IF NOT EXISTS idx_vehicle_sensors_sensor
    ON vehicle.vehicle_sensors(sensor_id);

-- ----------------------------------------------------------
-- 4. MANUALS / DOCUMENTATION
-- ----------------------------------------------------------

CREATE TABLE IF NOT EXISTS vehicle.documents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    vehicle_id UUID REFERENCES vehicle.vehicles(id) ON DELETE SET NULL,
    document_type TEXT NOT NULL,
    title TEXT NOT NULL,
    edition TEXT,
    language TEXT DEFAULT 'en',
    year INT,
    page_count INT,
    mime_type TEXT DEFAULT 'application/pdf',
    minio_bucket TEXT DEFAULT 'vehicle-documents',
    minio_key TEXT NOT NULL,
    file_size_bytes BIGINT,
    content_hash TEXT,
    source_url TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(content_hash)
);

CREATE INDEX IF NOT EXISTS idx_vehicle_docs_vehicle
    ON vehicle.documents(vehicle_id);
CREATE INDEX IF NOT EXISTS idx_vehicle_docs_type
    ON vehicle.documents(document_type);
CREATE INDEX IF NOT EXISTS idx_vehicle_docs_hash
    ON vehicle.documents(content_hash);
CREATE INDEX IF NOT EXISTS idx_vehicle_docs_type_vehicle
    ON vehicle.documents(document_type, vehicle_id);

-- ----------------------------------------------------------
-- 5. CROSS-REFERENCES (vehicle <-> refined schema)
-- ----------------------------------------------------------

-- Link DTC codes to specific vehicles
CREATE TABLE IF NOT EXISTS vehicle.vehicle_dtc_codes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    vehicle_id UUID NOT NULL REFERENCES vehicle.vehicles(id) ON DELETE CASCADE,
    dtc_id UUID NOT NULL REFERENCES refined.dtc_codes(id) ON DELETE CASCADE,
    prevalence TEXT,
    notes TEXT,
    confidence_score FLOAT DEFAULT 0.5
        CHECK (confidence_score >= 0 AND confidence_score <= 1),
    source_chunk_id UUID REFERENCES research.document_chunks(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(vehicle_id, dtc_id)
);

CREATE INDEX IF NOT EXISTS idx_vehicle_dtc_vehicle
    ON vehicle.vehicle_dtc_codes(vehicle_id);
CREATE INDEX IF NOT EXISTS idx_vehicle_dtc_dtc
    ON vehicle.vehicle_dtc_codes(dtc_id);

-- Link TSBs to specific vehicles
CREATE TABLE IF NOT EXISTS vehicle.vehicle_tsb_references (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    vehicle_id UUID NOT NULL REFERENCES vehicle.vehicles(id) ON DELETE CASCADE,
    tsb_id UUID NOT NULL REFERENCES refined.tsb_references(id) ON DELETE CASCADE,
    applicability_notes TEXT,
    confidence_score FLOAT DEFAULT 0.5
        CHECK (confidence_score >= 0 AND confidence_score <= 1),
    source_chunk_id UUID REFERENCES research.document_chunks(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(vehicle_id, tsb_id)
);

CREATE INDEX IF NOT EXISTS idx_vehicle_tsb_vehicle
    ON vehicle.vehicle_tsb_references(vehicle_id);
CREATE INDEX IF NOT EXISTS idx_vehicle_tsb_tsb
    ON vehicle.vehicle_tsb_references(tsb_id);

-- ==========================================================
-- VERIFICATION SCHEMA ADDITIONS
-- ==========================================================

ALTER TABLE refined.dtc_codes
    ADD COLUMN IF NOT EXISTS verified_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS verification_status TEXT DEFAULT 'unverified',
    ADD COLUMN IF NOT EXISTS verification_model TEXT,
    ADD COLUMN IF NOT EXISTS pre_verification_confidence FLOAT;

CREATE INDEX IF NOT EXISTS idx_dtc_verified
    ON refined.dtc_codes(verified_at NULLS FIRST);
CREATE INDEX IF NOT EXISTS idx_dtc_verification_status
    ON refined.dtc_codes(verification_status);

CREATE TABLE IF NOT EXISTS refined.verification_results (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    dtc_id UUID NOT NULL REFERENCES refined.dtc_codes(id) ON DELETE CASCADE,
    field_verified TEXT NOT NULL,
    original_value TEXT,
    verification_result TEXT NOT NULL,
    openai_response TEXT,
    confidence_adjustment FLOAT DEFAULT 0.0,
    model_used TEXT NOT NULL,
    api_key_id TEXT,
    tokens_used INT DEFAULT 0,
    verified_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_verification_dtc
    ON refined.verification_results(dtc_id);
CREATE INDEX IF NOT EXISTS idx_verification_result
    ON refined.verification_results(verification_result);
