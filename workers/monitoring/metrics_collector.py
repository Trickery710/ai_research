"""Metrics collection from all system components."""

import sys
import os
import requests
from datetime import datetime, timedelta

sys.path.insert(0, "/app")

from shared.redis_client import get_redis
from shared.db import execute_query


def collect_all_metrics() -> dict:
    """Collect metrics from all monitoring sources."""
    return {
        'timestamp': datetime.now().isoformat(),
        'queue_depths': collect_queue_depths(),
        'processing_stats': collect_processing_stats(),
        'stage_timings': collect_stage_timings(),
        'container_health': collect_container_health(),
        'document_stats': collect_document_stats(),
        'backend_health': collect_backend_health(),
        'llm_health': collect_llm_health()
    }


def collect_queue_depths() -> dict:
    """Get current depth of all Redis job queues."""
    try:
        redis_client = get_redis()
        queues = [
            "jobs:crawl", "jobs:chunk", "jobs:embed",
            "jobs:evaluate", "jobs:extract", "jobs:resolve"
        ]
        return {q: redis_client.llen(q) for q in queues}
    except Exception as e:
        print(f"[metrics] Failed to collect queue depths: {e}")
        return {}


def collect_processing_stats() -> dict:
    """Get success/failure counts per stage from processing_log."""
    try:
        # Last 1 hour of processing logs
        cutoff = datetime.now() - timedelta(hours=1)

        rows = execute_query(
            """SELECT stage, status, COUNT(*) as count
               FROM research.processing_log
               WHERE created_at > %s
               GROUP BY stage, status""",
            (cutoff,),
            fetch=True
        ) or []

        stats = {}
        for row in rows:
            stage = row['stage']
            if stage not in stats:
                stats[stage] = {'total': 0, 'completed': 0, 'failed': 0}

            count = row['count']
            stats[stage]['total'] += count

            if row['status'] == 'completed':
                stats[stage]['completed'] += count
            elif row['status'] == 'failed':
                stats[stage]['failed'] += count

        return stats
    except Exception as e:
        print(f"[metrics] Failed to collect processing stats: {e}")
        return {}


def collect_stage_timings() -> dict:
    """Calculate avg processing time per stage (recent vs historical)."""
    try:
        # Recent: last 50 completed jobs
        recent_rows = execute_query(
            """SELECT stage, AVG(duration_ms) as avg_ms
               FROM (
                   SELECT stage, duration_ms
                   FROM research.processing_log
                   WHERE status = 'completed' AND duration_ms IS NOT NULL
                   ORDER BY created_at DESC
                   LIMIT 50
               ) recent
               GROUP BY stage""",
            fetch=True
        ) or []

        # Historical: all time average
        historical_rows = execute_query(
            """SELECT stage, AVG(duration_ms) as avg_ms
               FROM research.processing_log
               WHERE status = 'completed' AND duration_ms IS NOT NULL
               GROUP BY stage""",
            fetch=True
        ) or []

        timings = {}
        for row in recent_rows:
            stage = row[0]
            timings[stage] = {'recent_avg_ms': float(row[1]) if row[1] else 0}

        for row in historical_rows:
            stage = row[0]
            if stage in timings:
                timings[stage]['historical_avg_ms'] = float(row[1]) if row[1] else 0
            else:
                timings[stage] = {'historical_avg_ms': float(row[1]) if row[1] else 0}

        return timings
    except Exception as e:
        print(f"[metrics] Failed to collect stage timings: {e}")
        return {}


def collect_container_health() -> dict:
    """Check health of all service containers via HTTP endpoints."""
    health_checks = {
        'backend': f"{os.environ.get('BACKEND_URL', 'http://backend:8000')}/health",
        'llm-embed': f"{os.environ.get('OLLAMA_EMBED_URL', 'http://llm-embed:11434')}/api/tags",
        'llm-reason': f"{os.environ.get('OLLAMA_REASON_URL', 'http://llm-reason:11434')}/api/tags"
    }

    results = {}
    for service, url in health_checks.items():
        try:
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                results[service] = {'status': 'healthy', 'unhealthy_since': None}
            else:
                results[service] = {
                    'status': 'unhealthy',
                    'unhealthy_since': datetime.now(),
                    'reason': f"HTTP {response.status_code}"
                }
        except requests.exceptions.RequestException as e:
            results[service] = {
                'status': 'unhealthy',
                'unhealthy_since': datetime.now(),
                'reason': str(e)
            }

    return results


def collect_document_stats() -> dict:
    """Get document processing statistics and stuck documents."""
    try:
        # Documents by stage
        stage_counts = execute_query(
            """SELECT processing_stage, COUNT(*) as count
               FROM research.documents
               GROUP BY processing_stage""",
            fetch=True
        ) or []

        by_stage = {row['processing_stage']: row['count'] for row in stage_counts}

        # Documents stuck in processing (> 30 minutes in same stage)
        cutoff = datetime.now() - timedelta(minutes=30)
        stuck_docs = execute_query(
            """SELECT id, processing_stage
               FROM research.documents
               WHERE processing_stage NOT IN ('completed', 'error', 'pending')
                 AND updated_at < %s""",
            (cutoff,),
            fetch=True
        ) or []

        stuck_by_stage = {}
        for doc in stuck_docs:
            stage = doc['processing_stage']
            if stage not in stuck_by_stage:
                stuck_by_stage[stage] = []
            stuck_by_stage[stage].append(str(doc['id']))

        return {
            'by_stage': by_stage,
            'stuck_documents': stuck_by_stage
        }
    except Exception as e:
        print(f"[metrics] Failed to collect document stats: {e}")
        return {'by_stage': {}, 'stuck_documents': {}}


def collect_backend_health() -> dict:
    """Get backend /health and /stats endpoints."""
    backend_url = os.environ.get('BACKEND_URL', 'http://backend:8000')

    try:
        health = requests.get(f"{backend_url}/health", timeout=5).json()
        stats = requests.get(f"{backend_url}/stats", timeout=5).json()
        return {'health': health, 'stats': stats, 'status': 'up'}
    except Exception as e:
        return {'status': 'down', 'error': str(e)}


def collect_llm_health() -> dict:
    """Check both Ollama instances are responding."""
    return {
        'embed': check_ollama(os.environ.get('OLLAMA_EMBED_URL', 'http://llm-embed:11434')),
        'reason': check_ollama(os.environ.get('OLLAMA_REASON_URL', 'http://llm-reason:11434'))
    }


def check_ollama(base_url: str) -> dict:
    """Check if Ollama is responding and list loaded models."""
    try:
        response = requests.get(f"{base_url}/api/tags", timeout=10)
        if response.status_code == 200:
            models = [m['name'] for m in response.json().get('models', [])]
            return {'status': 'healthy', 'models': models}
        else:
            return {'status': 'unhealthy', 'reason': f"HTTP {response.status_code}"}
    except Exception as e:
        return {'status': 'unhealthy', 'reason': str(e)}
