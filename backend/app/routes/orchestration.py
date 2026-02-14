"""Orchestration API endpoints for orchestrator, auditor, researcher, and coverage.

GET  /orchestrator/status   - Current orchestrator state
GET  /orchestrator/tasks    - List tasks with filtering
POST /orchestrator/command  - Submit manual command
GET  /audit/latest          - Latest audit report
GET  /audit/reports         - List audit reports
GET  /coverage              - Latest coverage snapshot
GET  /research/plans        - List research plans
GET  /research/sources      - List known sources
"""
import json
from fastapi import APIRouter, HTTPException

import redis

from app.config import Config
from app.db import execute_query, execute_query_one

router = APIRouter()

_redis_client = None


def _get_redis():
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis(
            host=Config.REDIS_HOST,
            port=Config.REDIS_PORT,
            decode_responses=True
        )
    return _redis_client


# ---- Orchestrator Endpoints ----

@router.get("/orchestrator/status")
def orchestrator_status():
    """Get current orchestrator state: latest cycle, task counts, queue depths."""
    r = _get_redis()

    # Latest orchestrator log entry
    latest_cycle = execute_query_one(
        """SELECT cycle_number, action, details, system_state, created_at
        FROM research.orchestrator_log
        ORDER BY created_at DESC LIMIT 1"""
    )

    # Task counts by status
    task_rows = execute_query(
        """SELECT status, COUNT(*) AS count
        FROM research.orchestrator_tasks
        GROUP BY status""",
        fetch=True
    )
    task_counts = {row["status"]: row["count"] for row in (task_rows or [])}

    # Queue depths
    queue_names = [
        "jobs:crawl", "jobs:chunk", "jobs:embed",
        "jobs:evaluate", "jobs:extract", "jobs:resolve",
        "orchestrator:research", "orchestrator:audit",
        "orchestrator:commands",
    ]
    queue_depths = {q: r.llen(q) for q in queue_names}

    return {
        "latest_cycle": {
            "cycle_number": latest_cycle["cycle_number"],
            "action": latest_cycle["action"],
            "details": latest_cycle["details"],
            "system_state": latest_cycle["system_state"],
            "timestamp": str(latest_cycle["created_at"]),
        } if latest_cycle else None,
        "task_counts": task_counts,
        "queue_depths": queue_depths,
    }


@router.get("/orchestrator/tasks")
def list_orchestrator_tasks(status: str = None, task_type: str = None,
                            limit: int = 50):
    """List orchestrator tasks with optional filtering."""
    conditions = []
    params = []

    if status:
        conditions.append("status = %s")
        params.append(status)
    if task_type:
        conditions.append("task_type = %s")
        params.append(task_type)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(limit)

    rows = execute_query(
        f"""SELECT id, task_type, status, priority, payload, assigned_to,
                   error_message, retry_count, created_at, started_at, completed_at
        FROM research.orchestrator_tasks
        {where}
        ORDER BY created_at DESC
        LIMIT %s""",
        tuple(params),
        fetch=True
    )
    return rows or []


@router.post("/orchestrator/command")
def submit_command(command: dict):
    """Submit a manual command to the orchestrator.

    Body should contain:
      - action: "trigger_audit" | "trigger_research" | "pause" | "resume"
      - target_codes: (optional) list of DTC codes for research
    """
    action = command.get("action")
    if not action:
        raise HTTPException(status_code=400, detail="Missing 'action' field")

    r = _get_redis()
    r.lpush("orchestrator:commands", json.dumps({
        "source": "api",
        "type": "manual_command",
        "action": action,
        "target_codes": command.get("target_codes", []),
    }))

    return {"status": "queued", "action": action}


# ---- Audit Endpoints ----

@router.get("/audit/latest")
def get_latest_audit():
    """Get the most recent audit report."""
    row = execute_query_one(
        """SELECT id, report_type, summary, metrics, recommendations, created_at
        FROM research.audit_reports
        ORDER BY created_at DESC LIMIT 1"""
    )
    if not row:
        return {"message": "No audit reports available"}

    return {
        "id": str(row["id"]),
        "report_type": row["report_type"],
        "summary": row["summary"],
        "metrics": row["metrics"],
        "recommendations": row["recommendations"],
        "created_at": str(row["created_at"]),
    }


@router.get("/audit/reports")
def list_audit_reports(report_type: str = None, limit: int = 20):
    """List audit reports, optionally filtered by type."""
    if report_type:
        rows = execute_query(
            """SELECT id, report_type, summary, created_at
            FROM research.audit_reports
            WHERE report_type = %s
            ORDER BY created_at DESC LIMIT %s""",
            (report_type, limit),
            fetch=True
        )
    else:
        rows = execute_query(
            """SELECT id, report_type, summary, created_at
            FROM research.audit_reports
            ORDER BY created_at DESC LIMIT %s""",
            (limit,),
            fetch=True
        )
    return rows or []


# ---- Coverage Endpoints ----

@router.get("/coverage")
def get_latest_coverage():
    """Get the latest coverage snapshot."""
    row = execute_query_one(
        """SELECT id, snapshot_date, total_dtc_codes, by_category,
                  by_confidence_tier, gap_ranges, completeness_score, created_at
        FROM research.coverage_snapshots
        ORDER BY snapshot_date DESC LIMIT 1"""
    )
    if not row:
        return {"message": "No coverage snapshots available"}

    return {
        "id": str(row["id"]),
        "snapshot_date": str(row["snapshot_date"]),
        "total_dtc_codes": row["total_dtc_codes"],
        "by_category": row["by_category"],
        "by_confidence_tier": row["by_confidence_tier"],
        "gap_ranges": row["gap_ranges"],
        "completeness_score": row["completeness_score"],
        "created_at": str(row["created_at"]),
    }


# ---- Research Endpoints ----

@router.get("/research/plans")
def list_research_plans(status: str = None, limit: int = 20):
    """List research plans."""
    if status:
        rows = execute_query(
            """SELECT id, plan_type, target_dtc_codes, target_topic,
                      priority, status, urls_submitted, urls_successful,
                      created_at, completed_at
            FROM research.research_plans
            WHERE status = %s
            ORDER BY created_at DESC LIMIT %s""",
            (status, limit),
            fetch=True
        )
    else:
        rows = execute_query(
            """SELECT id, plan_type, target_dtc_codes, target_topic,
                      priority, status, urls_submitted, urls_successful,
                      created_at, completed_at
            FROM research.research_plans
            ORDER BY created_at DESC LIMIT %s""",
            (limit,),
            fetch=True
        )
    return rows or []


@router.get("/research/sources")
def list_research_sources(limit: int = 50):
    """List known research sources and their quality metrics."""
    rows = execute_query(
        """SELECT id, domain, url_pattern, source_type, quality_tier,
                  last_crawled_at, total_urls_crawled, avg_trust_score,
                  is_blocked, created_at
        FROM research.research_sources
        ORDER BY quality_tier ASC, total_urls_crawled DESC
        LIMIT %s""",
        (limit,),
        fetch=True
    )
    return rows or []
