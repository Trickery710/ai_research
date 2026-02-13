#!/bin/bash
# Health monitoring script for AI Research Refinery

echo "=================================================="
echo "AI Research Refinery - Health Check"
echo "=================================================="
echo ""

# Container status
echo "📦 Container Status:"
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.State}}" --filter "name=refinery" | grep -E "NAME|refinery"
echo ""

# Health status
echo "🏥 Health Status:"
docker ps --format "table {{.Names}}\t{{.Status}}" --filter "name=refinery" | grep -E "healthy|unhealthy|starting" || echo "All containers running normally"
echo ""

# Check backend API
echo "🔌 Backend API:"
if curl -s -f http://localhost:8000/health > /dev/null 2>&1; then
    echo "✅ Backend API is responding"
else
    echo "❌ Backend API is not responding"
    echo "   Recent backend logs:"
    docker logs --tail 20 refinery_backend 2>&1 | tail -10
fi
echo ""

# Check database connection
echo "🗄️ Database Connection:"
if docker exec refinery_postgres pg_isready -U refinery -d refinery > /dev/null 2>&1; then
    echo "✅ PostgreSQL is ready"
    DB_CONNS=$(docker exec refinery_postgres psql -U refinery -d refinery -t -c "SELECT count(*) FROM pg_stat_activity WHERE datname='refinery';" 2>/dev/null | tr -d ' ')
    echo "   Active connections: ${DB_CONNS}"
else
    echo "❌ PostgreSQL is not ready"
fi
echo ""

# Check Redis
echo "📮 Redis:"
if docker exec refinery_redis redis-cli ping > /dev/null 2>&1; then
    echo "✅ Redis is responding"
    # Queue depths
    echo "   Queue depths:"
    for queue in "jobs:crawl" "jobs:chunk" "jobs:embed" "jobs:evaluate" "jobs:extract" "jobs:resolve"; do
        DEPTH=$(docker exec refinery_redis redis-cli llen "$queue" 2>/dev/null | tr -d '\r')
        echo "     - $queue: $DEPTH"
    done
else
    echo "❌ Redis is not responding"
fi
echo ""

# Check Ollama services
echo "🤖 LLM Services:"
if curl -s -f http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "✅ Ollama Embed (GPU ${GPU_EMBED:-all}) is responding"
    MODELS=$(curl -s http://localhost:11434/api/tags | grep -o '"name":"[^"]*"' | cut -d'"' -f4 | tr '\n' ', ')
    echo "   Models: ${MODELS}"
else
    echo "❌ Ollama Embed is not responding"
fi

if curl -s -f http://localhost:11435/api/tags > /dev/null 2>&1; then
    echo "✅ Ollama Reason (GPU ${GPU_REASON:-all}) is responding"
    MODELS=$(curl -s http://localhost:11435/api/tags | grep -o '"name":"[^"]*"' | cut -d'"' -f4 | tr '\n' ', ')
    echo "   Models: ${MODELS}"
else
    echo "❌ Ollama Reason is not responding"
fi
echo ""

# Pipeline stats
echo "📊 Pipeline Stats:"
if curl -s -f http://localhost:8000/stats > /dev/null 2>&1; then
    curl -s http://localhost:8000/stats | python3 -m json.tool 2>/dev/null || curl -s http://localhost:8000/stats
else
    echo "Unable to fetch stats (backend may be down)"
fi
echo ""

echo "=================================================="
echo "💡 Tip: Run 'watch -n 5 ./health-check.sh' for continuous monitoring"
echo "=================================================="
