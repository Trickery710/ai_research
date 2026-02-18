# AI Research Refinery -- Multi-Agent Architecture v2

This pack provides a complete multi-agent architecture for the Docker-compose, queue-driven AI pipeline (pgvector + Redis + MinIO + Ollama + FastAPI + workers). It combines **operational agents** (runtime issue response) with **development agents** (domain-specific code modification) under a master **orchestration agent**.

## Architecture Document
- `agents/00_ARCHITECTURE.md` -- Full technology map, domain breakdown, trigger matrix, validation pipeline

## Registry
- `agents/agent_registry.yaml` -- Canonical registry v2 (models, tools, scopes, categories, triggers)
- `agents/policy_schema.json` -- JSON schema for validation

## Agent Inventory

### Operational Agents (runtime response)
| # | Agent | File | Model | Purpose |
|---|-------|------|-------|---------|
| 01 | Triage | `01_triage.md` | haiku | First responder -- snapshot health, logs, queues, create error packet |
| 02 | Fix | `02_fix.md` | sonnet | Minimal patch writer -- smallest correct fix |
| 03 | Verify | `03_verify.md` | haiku | Prove the fix works -- health, logs, queue movement |
| 04 | Escalate | `04_escalate.md` | sonnet | Deep diagnosis when fix/verify cycles fail |
| 05 | Compose Auditor | `05_compose_auditor.md` | haiku | Audit docker-compose for reliability issues |
| 06 | Pipeline Operator | `06_pipeline_operator.md` | haiku | Queue stall recovery with minimal blast radius |

### Development Agents (domain-specific code modification)
| # | Agent | File | Model | Scope |
|---|-------|------|-------|-------|
| 10 | Backend API | `10_backend_api.md` | sonnet | backend/app/** |
| 11 | Pipeline Workers | `11_pipeline_workers.md` | sonnet | workers/{chunking,embedding,evaluation,extraction,conflict,crawler,verify}/** |
| 12 | Autonomous Agents | `12_autonomous_agents.md` | opus | workers/{orchestrator,researcher,auditor}/** |
| 13 | Monitoring & Healing | `13_monitoring_healing.md` | sonnet | workers/{monitoring,healing}/** |
| 14 | Shared Libraries | `14_shared_libraries.md` | sonnet | workers/shared/** |
| 15 | Database Schema | `15_database_schema.md` | opus | db/** |
| 16 | Infrastructure | `16_infrastructure.md` | sonnet | docker-compose.yml, observatory/**, Dockerfiles, requirements.txt |
| 17 | MCP Server | `17_mcp_server.md` | haiku | workers/mcp-server/** |

### Meta Agent (coordination)
| # | Agent | File | Model | Purpose |
|---|-------|------|-------|---------|
| 20 | Orchestrator | `20_orchestrator.md` | opus | Routes tasks, manages dependencies, resolves conflicts |

### Legacy Agents (preserved, superseded by development agents for their domains)
| Agent | File | Superseded By |
|-------|------|---------------|
| DB Optimizer | `db-optimizer.md` | Database Schema (15) |
| Docker Expert | `docker-containerization-expert.md` | Infrastructure (16) |

## Services (docker-compose.yml)

### Infrastructure
postgres (pgvector), redis 7, minio, searxng

### LLM (GPU)
llm-embed (GPU 0, nomic-embed-text), llm-reason (GPU 1, gemma3:12b), llm-eval (GPU 2, gemma3:12b)

### Backend
backend (FastAPI on :8000)

### Workers (Redis queue chain)
```
jobs:crawl -> jobs:chunk -> jobs:embed -> jobs:evaluate -> jobs:extract -> jobs:resolve
  crawler    chunking     embedding    evaluation      extraction     conflict
```
Also: worker-verify (self-driven timer, OpenAI gpt-4o-mini)

### Monitoring & Self-Healing
monitor-agent (:8001), healing-agent

### Autonomous Orchestration
orchestrator, researcher, auditor

### API
mcp-server (:8002, MCP SSE transport)

## Host Endpoints
- backend: http://localhost:8000/health
- monitor-agent: http://localhost:8001/health
- mcp-server: http://localhost:8002/health
- searxng: http://localhost:8080
- ollama embed: http://localhost:11434
- ollama reason: http://localhost:11435
- ollama eval: http://localhost:11436
- grafana: http://localhost:3000
- prometheus: http://localhost:9090

## Model Routing Strategy
- **Haiku**: Triage, Verify, Compose Auditor, Pipeline Operator, MCP Server
- **Sonnet**: Fix, Backend API, Pipeline Workers, Monitoring/Healing, Shared Libraries, Infrastructure
- **Opus**: Autonomous Agents, Database Schema, Orchestrator, Escalation ceiling

## Key Design Principles
1. **Mutually exclusive file scopes**: Each file belongs to exactly one development agent
2. **Operational vs Development split**: Runtime ops (01-06) do not overlap with code modification (10-17)
3. **Dependency-ordered execution**: Schema -> Shared -> Infra -> Domain agents -> Verification
4. **Safety-first healing**: Allow/deny lists, rate limits, confidence thresholds, audit logging
5. **GPU-aware**: 3-GPU topology encoded in infrastructure agent and docker-compose
