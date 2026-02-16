# AI Research Refinery — Production Agent Pack

This pack is designed for your Docker-compose, queue-driven AI pipeline (pgvector + Redis + MinIO + Ollama + FastAPI + workers).
It is optimized for **low tokens** via:
- tool-first triage
- strict log/file caps
- artifact-based context handoff (`artifacts/error_packet.md`)
- explicit model + tool permissions per agent
- controlled escalation

## Files
- `agents/agent_registry.yaml` — canonical registry (models, tools, scopes, caps, escalation)
- `agents/policy_schema.json` — JSON schema you can validate registry/agent configs against
- `agents/*.md` — agent role prompts (each includes YAML frontmatter + Model + Tools + Scope + Limits + Output contract)
- `artifacts/error_packet.md` — generated/updated by triage + verify

## Agents

| Agent | File | Model | Purpose |
|-------|------|-------|---------|
| Triage | `01_triage.md` | haiku | First responder — snapshot health, logs, queues, create error packet |
| Fix | `02_fix.md` | sonnet | Minimal patch writer — smallest correct fix |
| Verify | `03_verify.md` | haiku | Prove the fix works — health, logs, queue movement |
| Escalate | `04_escalate.md` | sonnet | Deep diagnosis when fix/verify cycles fail |
| Compose Auditor | `05_compose_auditor.md` | haiku | Audit docker-compose for reliability issues |
| Pipeline Operator | `06_pipeline_operator.md` | haiku | Queue stall recovery with minimal blast radius |
| DB Optimizer | `db-optimizer.md` | sonnet | Database query/schema optimization |
| Docker Expert | `docker-containerization-expert.md` | sonnet | Dockerfile/compose optimization and security |

## Services (docker-compose.yml)

### Infrastructure
postgres, redis, minio, searxng

### LLM (GPU)
llm-embed (GPU 0), llm-reason (GPU 1), llm-reason2 (GPU 1)

### Backend
backend (FastAPI on :8000)

### Workers (Redis queue chain)
jobs:crawl -> jobs:chunk -> jobs:embed -> jobs:evaluate -> jobs:extract -> jobs:resolve

worker-crawler, worker-chunking, worker-embedding, worker-evaluation, worker-extraction, worker-conflict, worker-verify

### Monitoring & Self-Healing
monitor-agent (:8001), healing-agent

### Autonomous Orchestration
orchestrator, researcher, auditor

### API
mcp-server (:8002)

## Host endpoints
- backend: http://localhost:8000/health
- monitor-agent: http://localhost:8001/health
- mcp-server: http://localhost:8002/health
- searxng: http://localhost:8080
- ollama embed: http://localhost:11434
- ollama reason: http://localhost:11435

## Intended routing (token-efficient)
- Triage / Verify / Compose audit / Pipeline ops: **Haiku**
- Fix / Escalate / DB optimizer / Docker expert: **Sonnet**
- Escalation ceiling: **Opus only when unavoidable**

> Tip: Turn on prompt caching for the agent prompts + your repo conventions to reduce repeated-token costs.
