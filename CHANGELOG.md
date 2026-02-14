# Changelog

All notable changes to AI Research Refinery will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

## [2.2.0] - 2026-02-14

### Added
- **Self-Healing Monitoring System**: Autonomous system health monitoring and auto-remediation
  - **Monitor Agent** (`monitor-agent` container on port 8001):
    - Continuous health monitoring every 45 seconds
    - Detects 5 types of anomalies: stalled queues, error rate spikes, processing slowdowns, unhealthy containers, stuck documents
    - Collects comprehensive metrics from all system components
    - Exposes HTTP endpoints: `/health`, `/metrics`, `/metrics/prometheus`
    - Sends structured alerts to Redis queue for healing agent
  - **Healing Agent** (`healing-agent` container):
    - LLM-powered error analysis using llama3 on `llm-reason` instance
    - Autonomous fix execution with safety controls
    - Available actions: `restart_worker`, `requeue_documents`, `clear_stale_locks`
    - Rate limiting: max 10 actions/hour with 2-minute cooldown between actions
    - Idempotency checks to prevent duplicate fixes
    - Comprehensive audit trail in `research.healing_log` table
  - **Safety Mechanisms**:
    - Allow/deny lists for action authorization
    - Confidence threshold ≥ 0.7 for automatic execution
    - Escalation to human for denied/low-confidence actions
    - All decisions logged with LLM reasoning for learning and compliance
  - **Database Schema**: New `research.healing_log` table with indexes for performance
    - Tracks all healing actions (executed, escalated, deferred)
    - Stores LLM reasoning, action results, and timestamps
    - Enables post-incident analysis and system learning

### Changed
- **Docker Compose**: Added 2 new services (monitor-agent, healing-agent) to stack
- **Configuration**: Environment-based tuning for monitoring thresholds and healing policies

### Technical Details
- New files:
  - `workers/monitoring/`: Complete monitoring agent implementation (6 files)
  - `workers/healing/`: Complete healing agent implementation (6 files)
  - `db/init.sql`: Added `research.healing_log` table schema
- Monitor agent metrics sources:
  - Redis queue depths via LLEN commands
  - PostgreSQL `research.processing_log` for error rates and timing
  - HTTP endpoints from backend, LLM services
  - Container health checks
- Healing agent uses:
  - Docker Python library for container management
  - Ollama LLM for analysis (low temperature=0.1 for conservative decisions)
  - Redis for rate limiting and deduplication
  - PostgreSQL for audit logging

### Performance
- Minimal overhead: monitoring cycle completes in <100ms
- Asynchronous alert processing via Redis queue
- Metrics retained for 24 hours by default (configurable)

---

## [2.1.0] - 2026-02-13

### Added
- **Self-Healing Infrastructure**: All containers now auto-restart on failure with `restart: unless-stopped` policy
- **Health Monitoring Script**: New `health-check.sh` script for comprehensive system monitoring
  - Container status and health checks
  - Database connection monitoring
  - Redis queue depth tracking
  - LLM service availability
  - Pipeline statistics
- **Database Connection Resilience**:
  - Connection validation before use (SELECT 1 test)
  - Automatic retry logic (2 attempts) on connection failures
  - TCP keepalive settings to detect dead connections proactively
  - Automatic connection pool recreation on persistent failures
  - Comprehensive error logging and diagnostics

### Fixed
- **Critical**: Fixed backend crashes caused by stale PostgreSQL connections
  - Error: `psycopg2.InterfaceError: connection already closed`
  - Added connection validation to prevent use of dead connections
  - Implemented automatic retry mechanism for transient failures
- **Database Connection Pool**: Enhanced both backend and worker connection management
  - Added timeout settings (10s connect timeout)
  - TCP keepalive configuration (30s idle, 10s interval, 5 retries)
  - Graceful connection cleanup on errors
- **Container Reliability**: Containers now automatically recover from crashes without manual intervention

### Changed
- **Backend Health Check**: Added 30s startup period to allow initialization before health checks
- **Error Handling**: Improved error recovery in all database query functions
- **Connection Management**: Enhanced `get_connection()` to validate and retry automatically

### Technical Details
- Modified `backend/app/db.py`: Enhanced connection pool with validation and retry logic
- Modified `workers/shared/db.py`: Enhanced worker connection pool with same improvements
- Modified `docker-compose.yml`: Added restart policies and health check improvements
- Added `FIXES_APPLIED.md`: Detailed documentation of the crash fix implementation

### Performance
- Minimal latency impact (~1ms per connection validation)
- No throughput degradation
- Significantly improved stability and uptime

---

## [2.0.0] - 2026-02-13

### Initial Release
- Multi-stage document processing pipeline (crawl → chunk → embed → evaluate → extract → resolve)
- Dual Ollama LLM instances with GPU assignment (embed + reasoning)
- PostgreSQL with pgvector for embeddings
- Redis-based job queuing
- MinIO object storage
- 6 specialized workers:
  - Crawler: Web scraping and content extraction
  - Chunking: Document segmentation
  - Embedding: Vector embeddings (nomic-embed-text)
  - Evaluation: Trust and relevance scoring (llama3)
  - Extraction: Structured data extraction (DTC codes, causes, diagnostics)
  - Conflict: Resolution of contradictory information
- REST API for document ingestion and search
- Health check endpoints for all services

---

## Legend

- **Added**: New features
- **Changed**: Changes to existing functionality
- **Deprecated**: Soon-to-be removed features
- **Removed**: Removed features
- **Fixed**: Bug fixes
- **Security**: Security improvements
