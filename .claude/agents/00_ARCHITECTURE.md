# AI Research Refinery -- Multi-Agent Architecture for Claude Code

Generated: 2026-02-18
Repository: /home/casey/project/ai_research

---

## 1. TECHNOLOGY MAP

```
Project Architecture Summary:
- Backend: Python 3 (FastAPI 0.129 + Uvicorn)
- Frontend: Static HTML dashboard (minimal, served by FastAPI)
- Database: PostgreSQL (pgvector) with 3 schemas: research, refined, knowledge + vehicle
- Object Storage: MinIO (documents, PDFs, raw text)
- Message Queue: Redis 7 (job queues: crawl -> chunk -> embed -> evaluate -> extract -> resolve)
- Auth: API key header (X-API-Key), configurable allow list
- LLM (Local): Ollama x3 instances (nomic-embed-text on GPU 0, gemma3:12b on GPU 1+2)
- LLM (Cloud): OpenAI API (gpt-4o-mini) for DTC verification, multi-key rotation
- Search: SearXNG (self-hosted meta-search for researcher)
- Infra: Docker Compose (20+ containers), NVIDIA GPU passthrough (3 GPUs)
- Monitoring: Prometheus + Grafana (observatory/), custom monitor-agent + healing-agent
- CI: Not detected
- Testing: Minimal (workers/conflict/test_scorer.py only)
- MCP: Model Context Protocol server (Starlette SSE transport, port 8002)
- Architecture: Microservices (queue-driven worker pipeline + autonomous agents)
- Domain: Automotive diagnostics knowledge engine (DTC codes, sensors, TSBs, vehicles)
```

### GPU Allocation
| GPU Slot | Hardware | Container | Model | Purpose |
|----------|----------|-----------|-------|---------|
| GPU 0 | Quadro P1000 4GB | llm-embed | nomic-embed-text | Vector embeddings (768-dim) |
| GPU 1 | RTX 3080 10GB | llm-reason | gemma3:12b | Extraction, evaluation, healing, orchestrator |
| GPU 2 | RTX 3070 8GB | llm-eval | gemma3:12b | Chunk evaluation (dedicated) |

### Redis Queue Pipeline
```
jobs:crawl -> jobs:chunk -> jobs:embed -> jobs:evaluate -> jobs:extract -> jobs:resolve
  crawler    chunking     embedding    evaluation      extraction     conflict (terminal)
```

### Database Schemas
| Schema | Purpose | Key Tables |
|--------|---------|------------|
| research | Raw/processing layer | documents, document_chunks, chunk_evaluations, crawl_queue, processing_log, healing_log, orchestrator_tasks |
| refined | Structured knowledge | dtc_codes, causes, diagnostic_steps, sensors, tsb_references, verification_results |
| knowledge | Normalized graph | dtc_master, dtc_possible_causes, dtc_verified_fixes, dtc_related_parts, dtc_symptoms, resolution_log |
| vehicle | Automotive reference | vehicles, engines, transmissions, sensor_part_numbers, vehicle_dtc_codes |

---

## 2. DOMAIN BREAKDOWN

| # | Domain | Directories / Files | Evidence |
|---|--------|---------------------|----------|
| 1 | Backend API | `backend/app/**`, `backend/Dockerfile`, `backend/requirements.txt`, `backend/main.py` | FastAPI routes, models, auth, config, DB pool |
| 2 | Pipeline Workers | `workers/chunking/**`, `workers/embedding/**`, `workers/evaluation/**`, `workers/extraction/**`, `workers/conflict/**`, `workers/crawler/**`, `workers/verify/**`, `worker/**` | Redis queue consumers, document processing stages |
| 3 | Autonomous Agents | `workers/orchestrator/**`, `workers/researcher/**`, `workers/auditor/**` | OODA loop orchestrator, SearXNG researcher, quality auditor |
| 4 | Monitoring & Healing | `workers/monitoring/**`, `workers/healing/**` | Anomaly detectors, metrics collector, healing executor with safety |
| 5 | Shared Libraries | `workers/shared/**` | Redis/DB/MinIO/Ollama/OpenAI clients, config, pipeline utilities, graceful shutdown |
| 6 | Database Schema | `db/init.sql`, `db/migrations/**` | 4 schemas, 40+ tables, pgvector indexes, knowledge graph |
| 7 | Infrastructure | `docker-compose.yml`, `observatory/**`, `searxng/**`, `scripts/**`, `health-check.sh`, `.env`, `config.yaml` | Docker Compose, Prometheus, Grafana, SearXNG config, GPU setup |
| 8 | MCP Server | `workers/mcp-server/**` | SSE transport, DTC lookup, semantic search, system stats tools |

---

## 3. SPECIALIZED AGENT DEFINITIONS

See individual agent files:
- `10_backend_api.md` -- Backend API Agent
- `11_pipeline_workers.md` -- Pipeline Workers Agent
- `12_autonomous_agents.md` -- Autonomous Agents Agent
- `13_monitoring_healing.md` -- Monitoring & Healing Agent
- `14_shared_libraries.md` -- Shared Libraries Agent
- `15_database_schema.md` -- Database Schema Agent (replaces db-optimizer.md)
- `16_infrastructure.md` -- Infrastructure Agent (replaces docker-containerization-expert.md)
- `17_mcp_server.md` -- MCP Server Agent
- `20_orchestrator.md` -- Master Orchestration Agent

---

## 4. MODEL ALLOCATION TABLE

| Agent | Model Tier | Justification |
|-------|-----------|---------------|
| Backend API | Sonnet | Moderate reasoning for route logic, Pydantic models, query construction |
| Pipeline Workers | Sonnet | Multi-file changes across queue chain, LLM prompt engineering |
| Autonomous Agents | Opus | Complex OODA loop logic, research planning, audit analysis |
| Monitoring & Healing | Sonnet | Safety-critical healing actions, anomaly detection logic |
| Shared Libraries | Sonnet | Cross-cutting library changes affect all workers |
| Database Schema | Opus | Complex multi-schema DDL, migration safety, pgvector indexing |
| Infrastructure | Sonnet | Docker Compose, GPU config, service dependencies |
| MCP Server | Haiku | Simple SSE server, tool handlers, straightforward CRUD |
| Orchestrator | Opus | Multi-domain coordination, conflict resolution, architecture decisions |
| Triage (existing) | Haiku | Snapshot collection, no reasoning needed |
| Fix (existing) | Sonnet | Minimal patch writing |
| Verify (existing) | Haiku | Command execution, pass/fail checks |
| Escalate (existing) | Sonnet/Opus | Deep multi-service diagnosis |

---

## 5. TRIGGER MATRIX

| Trigger Pattern | Primary Agent | Secondary Agent | Condition |
|-----------------|---------------|-----------------|-----------|
| `backend/app/routes/**` modified | Backend API | -- | Any change |
| `backend/app/models.py` modified | Backend API | Database Schema | If new fields added |
| `backend/app/db.py` modified | Backend API | Shared Libraries | Connection pool changes |
| `backend/app/auth.py` modified | Backend API | -- | Any change |
| `backend/app/config.py` modified | Backend API | Infrastructure | If new env vars |
| `backend/Dockerfile` modified | Infrastructure | -- | Any change |
| `workers/chunking/**` modified | Pipeline Workers | -- | Any change |
| `workers/embedding/**` modified | Pipeline Workers | -- | Any change |
| `workers/evaluation/**` modified | Pipeline Workers | -- | Any change |
| `workers/extraction/**` modified | Pipeline Workers | -- | Any change |
| `workers/conflict/**` modified | Pipeline Workers | Database Schema | If SQL queries change |
| `workers/crawler/**` modified | Pipeline Workers | -- | Any change |
| `workers/verify/**` modified | Pipeline Workers | -- | Any change |
| `workers/orchestrator/**` modified | Autonomous Agents | -- | Any change |
| `workers/researcher/**` modified | Autonomous Agents | -- | Any change |
| `workers/auditor/**` modified | Autonomous Agents | -- | Any change |
| `workers/monitoring/**` modified | Monitoring & Healing | -- | Any change |
| `workers/healing/**` modified | Monitoring & Healing | -- | Any change |
| `workers/shared/**` modified | Shared Libraries | Pipeline Workers | Cross-cutting impact |
| `db/init.sql` modified | Database Schema | Backend API | Schema changes affect queries |
| `db/migrations/**` added | Database Schema | -- | New migration |
| `docker-compose.yml` modified | Infrastructure | Monitoring & Healing | If ports/volumes/GPU change |
| `observatory/**` modified | Infrastructure | -- | Prometheus/Grafana config |
| `workers/mcp-server/**` modified | MCP Server | -- | Any change |
| `.env` modified | Infrastructure | -- | Env var changes |
| `config.yaml` modified | Infrastructure | -- | Model/GPU config |
| `**/requirements.txt` modified | Infrastructure | Pipeline Workers | Dependency changes |
| `**/Dockerfile` modified | Infrastructure | -- | Build changes |
| Container health failure | Triage (existing) | Monitoring & Healing | Runtime event |
| Queue stall detected | Pipeline Operator (existing) | Monitoring & Healing | Runtime event |
| Test failure | Pipeline Workers | -- | If test files exist |

---

## 6. VALIDATION PIPELINE

```
                    Task Received
                         |
                    [Orchestrator]
                    /    |    \
                   /     |     \
          [Agent A] [Agent B] [Agent C]   <-- parallel if independent
              |        |         |
          validate  validate  validate    <-- per-agent validation
              \        |        /
               \       |       /
            [Orchestrator Consistency Check]
                       |
              [Cross-agent file overlap check]
                       |
              [Docker build verification]
                       |
              [Queue pipeline integrity check]
                       |
                   COMPLETE
```

### Per-Agent Validation Requirements
| Agent | Validation |
|-------|-----------|
| Backend API | `python -m py_compile backend/app/main.py`, FastAPI import check |
| Pipeline Workers | `python -m py_compile` on modified worker, queue chain intact |
| Autonomous Agents | `python -m py_compile`, Redis queue names consistent |
| Monitoring & Healing | Safety allow/deny lists unchanged unless intentional |
| Shared Libraries | All importing workers still compile |
| Database Schema | SQL syntax valid, migrations are additive (no DROP without explicit approval) |
| Infrastructure | `docker compose config --quiet` passes, no port conflicts |
| MCP Server | `python -m py_compile workers/mcp-server/server.py` |

---

## 7. ORCHESTRATION AGENT

See `20_orchestrator.md` for full specification.

### Summary

**Task Intake**: Parse affected files, classify by domain using trigger matrix.

**Agent Selection**: Match trigger patterns, identify all affected agents for multi-domain tasks.

**Parallelization Rules**:
- Independent domains execute in parallel
- Database schema changes complete before API/worker changes
- Shared library changes complete before all worker changes
- Infrastructure changes complete before rebuild-dependent agents
- Triage/Verify agents run sequentially after code-modifying agents

**Conflict Resolution**:
- File ownership is strictly enforced by glob patterns
- If two agents need the same file: orchestrator reviews and assigns to primary owner
- Maximum retry count per agent: 3
- Maximum orchestration cycles per task: 10

**Loop Prevention**:
- Track agent invocation counts per task ID
- Hard limit: no agent invoked more than 5 times per task
- Halt and report to human if limit reached
