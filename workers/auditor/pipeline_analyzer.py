"""Analyzes pipeline performance: throughput, error rates, bottlenecks."""
from shared.db import execute_query, execute_query_one
from shared.redis_client import get_redis


PIPELINE_STAGES = [
    "crawling", "chunking", "embedding", "evaluating", "extracting", "resolving"
]

PIPELINE_QUEUES = [
    "jobs:crawl", "jobs:chunk", "jobs:embed",
    "jobs:evaluate", "jobs:extract", "jobs:resolve"
]


def analyze_throughput(hours=24):
    """Compute documents processed per hour over the last N hours.

    Args:
        hours: Lookback window in hours.

    Returns:
        dict with throughput metrics per stage.
    """
    rows = execute_query(
        """SELECT stage, status, COUNT(*) AS count,
            AVG(duration_ms) AS avg_duration_ms
        FROM research.processing_log
        WHERE created_at > NOW() - INTERVAL '%s hours'
        GROUP BY stage, status
        ORDER BY stage, status""",
        (hours,),
        fetch=True
    )

    stage_stats = {}
    for row in (rows or []):
        stage, status, count, avg_ms = row
        if stage not in stage_stats:
            stage_stats[stage] = {
                "completed": 0, "failed": 0, "started": 0,
                "avg_duration_ms": 0
            }
        stage_stats[stage][status] = count
        if status == "completed" and avg_ms:
            stage_stats[stage]["avg_duration_ms"] = round(float(avg_ms), 1)

    # Compute per-hour rates
    for stage, stats in stage_stats.items():
        completed = stats.get("completed", 0)
        stats["docs_per_hour"] = round(completed / max(hours, 1), 2)

    return {
        "window_hours": hours,
        "stages": stage_stats,
    }


def analyze_error_rates(hours=24):
    """Compute error rates per pipeline stage.

    Returns:
        dict with error rate per stage and list of stuck documents.
    """
    rows = execute_query(
        """SELECT stage,
            COUNT(*) FILTER (WHERE status = 'completed') AS completed,
            COUNT(*) FILTER (WHERE status = 'failed') AS failed,
            COUNT(*) AS total
        FROM research.processing_log
        WHERE created_at > NOW() - INTERVAL '%s hours'
        GROUP BY stage""",
        (hours,),
        fetch=True
    )

    error_rates = {}
    for row in (rows or []):
        stage, completed, failed, total = row
        rate = failed / total if total > 0 else 0
        error_rates[stage] = {
            "completed": completed,
            "failed": failed,
            "total": total,
            "error_rate": round(rate, 4),
        }

    # Find documents stuck in error state
    stuck = execute_query(
        """SELECT id, title, processing_stage, error_message, updated_at
        FROM research.documents
        WHERE processing_stage = 'error'
        ORDER BY updated_at DESC
        LIMIT 20""",
        fetch=True
    )

    stuck_docs = [
        {
            "id": str(r[0]),
            "title": r[1],
            "stage": r[2],
            "error": r[3][:200] if r[3] else None,
            "updated_at": str(r[4]),
        }
        for r in (stuck or [])
    ]

    return {
        "window_hours": hours,
        "error_rates": error_rates,
        "stuck_documents": stuck_docs,
        "stuck_count": len(stuck_docs),
    }


def detect_bottleneck():
    """Identify the pipeline bottleneck by comparing queue depths and processing times.

    Returns:
        dict with bottleneck stage and queue depth info.
    """
    r = get_redis()

    queue_depths = {}
    for queue in PIPELINE_QUEUES:
        queue_depths[queue] = r.llen(queue)

    # Find the queue with highest depth
    bottleneck_queue = max(queue_depths, key=queue_depths.get) if queue_depths else None
    max_depth = queue_depths.get(bottleneck_queue, 0) if bottleneck_queue else 0

    # Get average processing times per stage
    timing_rows = execute_query(
        """SELECT stage, AVG(duration_ms) AS avg_ms
        FROM research.processing_log
        WHERE status = 'completed'
            AND created_at > NOW() - INTERVAL '24 hours'
        GROUP BY stage
        ORDER BY avg_ms DESC""",
        fetch=True
    )

    slowest_stage = None
    stage_timings = {}
    for row in (timing_rows or []):
        stage, avg_ms = row
        stage_timings[stage] = round(float(avg_ms), 1) if avg_ms else 0
        if slowest_stage is None:
            slowest_stage = stage

    total_queued = sum(queue_depths.values())

    return {
        "queue_depths": queue_depths,
        "total_queued": total_queued,
        "bottleneck_queue": bottleneck_queue if max_depth > 0 else None,
        "bottleneck_depth": max_depth,
        "slowest_stage": slowest_stage,
        "stage_timings_ms": stage_timings,
    }


def get_pipeline_summary():
    """Get a combined pipeline health summary."""
    throughput = analyze_throughput(hours=24)
    errors = analyze_error_rates(hours=24)
    bottleneck = detect_bottleneck()

    # Determine overall pipeline health
    health = "healthy"
    issues = []

    if errors["stuck_count"] > 5:
        health = "degraded"
        issues.append(f"{errors['stuck_count']} documents stuck in error state")

    for stage, stats in errors["error_rates"].items():
        if stats["error_rate"] > 0.15:
            health = "degraded"
            issues.append(f"{stage} error rate: {stats['error_rate']:.1%}")

    if bottleneck["total_queued"] > 50:
        health = "busy"
        issues.append(f"{bottleneck['total_queued']} total items queued")

    return {
        "health": health,
        "issues": issues,
        "throughput": throughput,
        "errors": errors,
        "bottleneck": bottleneck,
    }
