#!/bin/bash
# Safe shutdown script for AI Research Refinery
#
# Stops the stack in reverse dependency order:
#   1. Autonomous agents (orchestrator, researcher, auditor) - stop directing work
#   2. Monitoring & healing - stop auto-remediation
#   3. Pipeline workers - drain queues gracefully
#   4. Backend API & MCP server - stop accepting new work
#   5. LLM services - free GPU memory
#   6. Infrastructure (postgres, redis, minio, searxng) - last to go
#
# Usage:
#   ./scripts/stop-stack.sh          # Stop everything
#   ./scripts/stop-stack.sh workers  # Stop only workers (keep infra running)
#   ./scripts/stop-stack.sh agents   # Stop only autonomous agents
#   ./scripts/stop-stack.sh --force  # Skip grace period, stop immediately

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_FILE="$PROJECT_DIR/docker-compose.yml"
GRACE_PERIOD=10  # seconds to wait between tiers
FORCE=false
TARGET="all"

# Parse arguments
for arg in "$@"; do
    case "$arg" in
        --force|-f)  FORCE=true ;;
        workers)     TARGET="workers" ;;
        agents)      TARGET="agents" ;;
        monitoring)  TARGET="monitoring" ;;
        llm)         TARGET="llm" ;;
        infra)       TARGET="infra" ;;
        --help|-h)
            echo "Usage: $0 [target] [--force]"
            echo ""
            echo "Targets:"
            echo "  all         Stop the entire stack (default)"
            echo "  agents      Stop autonomous agents (orchestrator, researcher, auditor)"
            echo "  monitoring  Stop monitor + healing agents"
            echo "  workers     Stop all pipeline workers"
            echo "  llm         Stop LLM/Ollama services"
            echo "  infra       Stop infrastructure (postgres, redis, minio, searxng)"
            echo ""
            echo "Options:"
            echo "  --force, -f  Skip grace periods between tiers"
            exit 0
            ;;
        *)
            echo "Unknown argument: $arg (use --help for usage)"
            exit 1
            ;;
    esac
done

# Service groups (reverse dependency order)
AUTONOMOUS="orchestrator researcher auditor"
MONITORING="healing-agent monitor-agent"
PIPELINE_WORKERS="worker-verify worker-extraction worker-evaluation worker-embedding worker-chunking worker-conflict worker-crawler"
API_SERVICES="mcp-server backend"
LLM_SERVICES="llm-eval llm-reason llm-embed"
INFRASTRUCTURE="searxng minio redis postgres"

stop_services() {
    local label="$1"
    shift
    local services="$*"

    # Check if any are running
    local running=""
    for svc in $services; do
        if docker compose -f "$COMPOSE_FILE" ps --status running "$svc" 2>/dev/null | grep -q "$svc"; then
            running="$running $svc"
        fi
    done

    if [ -z "$running" ]; then
        echo "  (all already stopped)"
        return
    fi

    echo "  Stopping:$running"
    docker compose -f "$COMPOSE_FILE" stop $running 2>&1 | sed 's/^/    /'

    if [ "$FORCE" = false ]; then
        echo "  Waiting ${GRACE_PERIOD}s for clean shutdown..."
        sleep "$GRACE_PERIOD"
    fi
}

drain_queues() {
    echo "  Checking queue depths before stopping workers..."
    local has_items=false
    for queue in "jobs:crawl" "jobs:chunk" "jobs:embed" "jobs:evaluate" "jobs:extract" "jobs:resolve"; do
        depth=$(docker exec refinery_redis redis-cli llen "$queue" 2>/dev/null | tr -d '\r' || echo "?")
        if [ "$depth" != "0" ] && [ "$depth" != "?" ]; then
            echo "    $queue: $depth items (will be preserved in Redis)"
            has_items=true
        fi
    done
    if [ "$has_items" = true ]; then
        echo "  Note: Queue items are preserved in Redis and will resume on restart."
    else
        echo "  All queues are empty."
    fi
}

echo "=================================================="
echo "AI Research Refinery - Safe Shutdown"
echo "=================================================="
echo "Target: $TARGET"
echo ""

case "$TARGET" in
    all)
        echo "[1/6] Stopping autonomous agents..."
        stop_services "autonomous" $AUTONOMOUS

        echo "[2/6] Stopping monitoring & healing..."
        stop_services "monitoring" $MONITORING

        echo "[3/6] Draining & stopping pipeline workers..."
        drain_queues
        stop_services "workers" $PIPELINE_WORKERS

        echo "[4/6] Stopping API services..."
        stop_services "api" $API_SERVICES

        echo "[5/6] Stopping LLM services..."
        stop_services "llm" $LLM_SERVICES

        echo "[6/6] Stopping infrastructure..."
        GRACE_PERIOD=5
        stop_services "infra" $INFRASTRUCTURE
        ;;
    agents)
        echo "Stopping autonomous agents..."
        stop_services "autonomous" $AUTONOMOUS
        ;;
    monitoring)
        echo "Stopping monitoring & healing..."
        stop_services "monitoring" $MONITORING
        ;;
    workers)
        echo "Stopping pipeline workers..."
        drain_queues
        stop_services "workers" $PIPELINE_WORKERS
        ;;
    llm)
        echo "Stopping LLM services..."
        stop_services "llm" $LLM_SERVICES
        ;;
    infra)
        echo "Stopping infrastructure..."
        stop_services "infra" $INFRASTRUCTURE
        ;;
esac

echo ""
echo "Done. Remaining containers:"
docker compose -f "$COMPOSE_FILE" ps --format "table {{.Name}}\t{{.Status}}\t{{.State}}" 2>/dev/null || echo "  (none running)"
echo ""
echo "To restart: docker compose -f $COMPOSE_FILE up -d"
echo "=================================================="
