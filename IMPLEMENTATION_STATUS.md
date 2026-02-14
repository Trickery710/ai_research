# Self-Healing Monitoring System - Implementation Status

## Overview
Adding two new containers: `monitor-agent` (detects anomalies) and `healing-agent` (auto-fixes issues with LLM analysis).

## Progress Summary

### ✅ Completed

#### Phase 1: Monitoring Agent (Partial)
- [x] Directory structure created: `workers/monitoring/`
- [x] Dockerfile created with Python 3.11-slim base
- [x] requirements.txt created (psycopg2, redis, requests, flask)
- [x] **metrics_collector.py** implemented (COMPLETE)
  - Collects queue depths from Redis
  - Queries processing stats from database
  - Checks container health via HTTP
  - Monitors document processing state
  - Tracks LLM service availability

### ⏳ In Progress / TODO

#### Phase 1: Monitoring Agent (Remaining)
- [ ] **detectors.py** - Implement 5 anomaly detection functions:
  - `detect_stalled_queues()` - Queue depth unchanged for 5+ min
  - `detect_error_rate_spikes()` - >15% failure rate
  - `detect_processing_time_anomalies()` - 3x slower than average
  - `detect_unhealthy_containers()` - Health check failures
  - `detect_stuck_documents()` - Documents stuck >30 min
- [ ] **http_server.py** - Flask server for metrics endpoint (port 8001)
  - `/health` - Monitor agent health check
  - `/metrics` - JSON metrics dump
  - `/metrics/prometheus` - Prometheus format export
- [ ] **worker.py** - Main monitoring loop
  - Run monitoring cycle every 45s
  - Store metrics in Redis with retention
  - Send alerts to `monitoring:alerts` queue
  - Handle errors gracefully

#### Phase 2: Healing Agent
- [ ] Create `workers/healing/` directory structure
- [ ] **Dockerfile** - Base image + Docker CLI + optional Claude Code
- [ ] **requirements.txt** - psycopg2, redis, docker Python library
- [ ] **safety.py** - Rate limiting, allow/deny lists, idempotency
- [ ] **audit_logger.py** - Log all healing actions to DB
- [ ] **analyzer.py** - LLM-based error analysis
  - System prompt for DevOps expert persona
  - JSON parsing with fallback strategies
  - Confidence scoring
- [ ] **executor.py** - Action execution engine
  - `restart_worker()` - Docker restart
  - `requeue_documents()` - Redis + DB
  - `clear_stale_locks()` - Redis cleanup
  - `escalate_to_human()` - Notification logging
- [ ] **worker.py** - Main healing loop
  - Consume alerts from Redis queue
  - Analyze with LLM
  - Execute safe actions
  - Log to audit trail

#### Phase 3: Database & Docker Integration
- [ ] Add `healing_log` table to `db/init.sql`
- [ ] Add `monitor-agent` service to `docker-compose.yml`
- [ ] Add `healing-agent` service to `docker-compose.yml`

#### Phase 4: Testing & Deployment
- [ ] Build monitor-agent container
- [ ] Build healing-agent container
- [ ] Test monitoring detection with simulated failures
- [ ] Test healing actions (restart worker, requeue docs)
- [ ] Verify rate limiting and safety mechanisms
- [ ] Fine-tune thresholds based on real behavior

## File Tree

```
workers/
├── monitoring/                    # Monitor Agent
│   ├── Dockerfile                ✅ Created
│   ├── requirements.txt          ✅ Created
│   ├── metrics_collector.py      ✅ Implemented
│   ├── detectors.py              ⏳ TODO
│   ├── http_server.py            ⏳ TODO
│   └── worker.py                 ⏳ TODO
│
├── healing/                       # Healing Agent
│   ├── Dockerfile                ⏳ TODO
│   ├── requirements.txt          ⏳ TODO
│   ├── safety.py                 ⏳ TODO
│   ├── audit_logger.py           ⏳ TODO
│   ├── analyzer.py               ⏳ TODO
│   ├── executor.py               ⏳ TODO
│   └── worker.py                 ⏳ TODO
│
└── shared/                        # Reuse existing
    ├── config.py                 ✅ Exists
    ├── db.py                     ✅ Exists
    ├── redis_client.py           ✅ Exists
    └── ollama_client.py          ✅ Exists
```

## Next Steps

1. **Continue Phase 1:** Implement `detectors.py`, `http_server.py`, and `worker.py` for monitoring
2. **Build & Test Monitor:** `docker compose build monitor-agent && docker compose up -d monitor-agent`
3. **Verify Metrics:** `curl http://localhost:8001/metrics | jq`
4. **Proceed to Phase 2:** Implement healing agent components
5. **Integration Testing:** Simulate failures and verify detection → healing flow

## Reference Implementation Patterns

For implementing remaining files, refer to these existing files:

- **Worker loop pattern:** `workers/evaluation/worker.py` (lines 171-196)
- **LLM integration:** `workers/shared/ollama_client.py`
- **Database queries:** `workers/shared/db.py`
- **Redis queue ops:** `workers/shared/redis_client.py`
- **Docker service def:** `docker-compose.yml` (existing worker definitions)

## Configuration (Conservative Start)

```yaml
# Start with these settings for testing
MONITOR_INTERVAL: "60"           # 1 minute
QUEUE_STALL_THRESHOLD: "600"     # 10 minutes
MAX_ACTIONS_PER_HOUR: "5"        # Strict limit
AUTO_FIX_ENABLED: "false"        # Escalate-only mode
```

Once validated, switch to production settings (45s interval, 5min threshold, auto-fix enabled).

## Estimated Completion Time

- Remaining Phase 1: ~2-3 hours
- Phase 2 (Healing Agent): ~3-4 hours
- Phase 3 (Integration): ~1-2 hours
- Phase 4 (Testing): ~2-3 hours

**Total:** ~8-12 hours of development

This is a multi-session implementation. Prioritize Phase 1 completion first to have working monitoring, then add healing capabilities.
