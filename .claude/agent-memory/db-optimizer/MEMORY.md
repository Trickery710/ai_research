# DB Optimizer Agent Memory

## Project: AI Research Refinery v2

### Database Engine
- PostgreSQL with pgvector extension (VECTOR(768) embeddings)
- uuid-ossp extension for UUID PKs (uuid_generate_v4())

### Schema Layout
- `research` - Raw/processing layer (documents, chunks, evaluations, crawl_queue, orchestrator)
- `refined` - Structured knowledge layer (dtc_codes, causes, diagnostic_steps, sensors, tsb_references)
- `vehicle` - Automotive reference data (vehicles, engines, transmissions, sensors, documents)
- `knowledge` - Normalized DTC knowledge graph (added via migration 0001)

### Key Conventions
- All PKs: UUID DEFAULT uuid_generate_v4()
- All timestamps: TIMESTAMP WITH TIME ZONE DEFAULT NOW()
- Score fields: FLOAT with CHECK (val >= 0 AND val <= 1)
- IF NOT EXISTS on all CREATE TABLE/INDEX/SCHEMA
- Soft deletes not used; CASCADE on junction tables, SET NULL on optional FKs

### Important File Paths
- Init schema: `db/init.sql`
- Migrations: `db/migrations/`
- 0001: knowledge schema (21 tables - dtc_master, symptoms, causes, fixes, parts, sensors, etc.)
- 0002: entity source provenance + resolution audit log
- 0003: compatibility views (knowledge.* -> refined.v_* shape)

### Cross-Schema References
- vehicle.sensor_part_numbers -> refined.sensors(id)
- vehicle.vehicle_sensors -> refined.sensors(id)
- vehicle.vehicle_dtc_codes -> refined.dtc_codes(id)
- vehicle.vehicle_tsb_references -> refined.tsb_references(id)
- knowledge.vehicle_dtc_occurrence -> vehicle.vehicles(id)
- knowledge.dtc_entity_sources -> research.document_chunks(id)
