"""Strategic planning: decides which DTC ranges to research next.

Uses rule-based logic for routine decisions and LLM for strategic planning.
"""
import json
import os
from shared.db import execute_query, execute_query_one
from shared.ollama_client import generate_completion

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://llm-reason:11434")
REASONING_MODEL = os.environ.get("REASONING_MODEL", "llama3")


def get_latest_audit_report():
    """Fetch the most recent audit report.

    Returns:
        dict with report data or None.
    """
    row = execute_query_one(
        """SELECT id, report_type, summary, metrics, recommendations, created_at
        FROM research.audit_reports
        ORDER BY created_at DESC
        LIMIT 1"""
    )
    if not row:
        return None

    return {
        "id": str(row[0]),
        "report_type": row[1],
        "summary": row[2],
        "metrics": row[3] if isinstance(row[3], dict) else json.loads(row[3]) if row[3] else {},
        "recommendations": row[4] if isinstance(row[4], list) else json.loads(row[4]) if row[4] else [],
        "created_at": str(row[5]),
    }


def get_latest_coverage_snapshot():
    """Fetch the most recent coverage snapshot.

    Returns:
        dict or None.
    """
    row = execute_query_one(
        """SELECT snapshot_date, total_dtc_codes, by_category,
                  by_confidence_tier, gap_ranges, completeness_score
        FROM research.coverage_snapshots
        ORDER BY snapshot_date DESC
        LIMIT 1"""
    )
    if not row:
        return None

    return {
        "snapshot_date": str(row[0]),
        "total_dtc_codes": row[1],
        "by_category": row[2] if isinstance(row[2], dict) else json.loads(row[2]) if row[2] else {},
        "by_confidence_tier": row[3] if isinstance(row[3], dict) else json.loads(row[3]) if row[3] else {},
        "gap_ranges": row[4] if isinstance(row[4], list) else json.loads(row[4]) if row[4] else [],
        "completeness_score": float(row[5]) if row[5] else 0,
    }


def decide_next_actions(system_state, audit_report=None):
    """Rule-based decision engine for the orchestrator.

    Priority order:
    1. System health issues -> fix pipeline
    2. Pipeline processing -> wait for completion
    3. Audit needed (>30min since last) -> trigger audit
    4. High-priority research from audit findings
    5. Improve low-confidence codes
    6. Expand coverage into gap ranges

    Args:
        system_state: From resource_monitor.get_system_state().
        audit_report: Latest audit report dict or None.

    Returns:
        list of action dicts to execute.
    """
    actions = []

    # Priority 1: System health
    if system_state.get("total_queued", 0) > 50:
        actions.append({
            "type": "wait",
            "reason": "Pipeline heavily loaded",
            "priority": 1,
        })
        return actions  # Don't add more work

    # Priority 2: Pipeline busy - defer
    if not system_state.get("pipeline_idle", True) and \
       not system_state.get("gpu_available", True):
        actions.append({
            "type": "wait",
            "reason": "GPU resources busy, deferring new work",
            "priority": 2,
        })
        return actions

    # Priority 3: Check if audit is needed
    if not audit_report:
        actions.append({
            "type": "trigger_audit",
            "reason": "No audit reports found - running initial audit",
            "priority": 3,
        })

    # If we have audit data, use recommendations to drive research
    if audit_report:
        recommendations = audit_report.get("recommendations", [])

        for rec in recommendations:
            rec_type = rec.get("type")
            rec_priority = rec.get("priority", 5)

            # Priority 1-2: Pipeline fixes (handled by healing agent)
            if rec_type in ("fix_pipeline", "reprocess_errors"):
                actions.append({
                    "type": "alert",
                    "reason": rec.get("description", "Pipeline issue detected"),
                    "priority": rec_priority,
                })
                continue

            # Priority 4-5: Research to improve confidence
            if rec_type == "improve_confidence" and \
               system_state.get("crawl_available", False):
                codes = rec.get("target_codes", [])
                if codes:
                    actions.append({
                        "type": "research",
                        "subtype": "improve_confidence",
                        "target_codes": codes,
                        "reason": rec.get("description"),
                        "priority": 5,
                    })

            # Priority 4: Fill gaps in existing codes
            if rec_type == "fill_gaps" and \
               system_state.get("crawl_available", False):
                codes = rec.get("target_codes", [])
                if codes:
                    actions.append({
                        "type": "research",
                        "subtype": "fill_gaps",
                        "target_codes": codes,
                        "reason": rec.get("description"),
                        "priority": 4,
                    })

            # Priority 6: Coverage expansion
            if rec_type == "expand_coverage" and \
               system_state.get("crawl_available", False):
                ranges = rec.get("target_ranges", [])
                if ranges:
                    actions.append({
                        "type": "research",
                        "subtype": "expand_coverage",
                        "target_ranges": ranges,
                        "reason": rec.get("description"),
                        "priority": 6,
                    })

    # If pipeline is idle and no actions yet, check for proactive research
    if not actions and system_state.get("pipeline_idle", False):
        actions.append({
            "type": "idle",
            "reason": "Pipeline idle, no outstanding actions",
            "priority": 7,
        })

    # Sort by priority
    actions.sort(key=lambda a: a.get("priority", 99))
    return actions


def generate_strategic_plan(audit_report, coverage_snapshot):
    """Use LLM to generate a strategic research plan.

    Called periodically (e.g., daily) for higher-level planning.

    Args:
        audit_report: Latest audit report dict.
        coverage_snapshot: Latest coverage snapshot dict.

    Returns:
        dict with plan details or None on failure.
    """
    if not audit_report or not coverage_snapshot:
        return None

    prompt = f"""You are an automotive diagnostics research planner. Based on the current
state of our knowledge base, suggest the most valuable DTC code ranges to research next.

Current state:
- Total DTC codes: {coverage_snapshot.get('total_dtc_codes', 0)}
- Coverage by category: {json.dumps(coverage_snapshot.get('by_category', {}))}
- Confidence tiers: {json.dumps(coverage_snapshot.get('by_confidence_tier', {}))}
- Completeness score: {coverage_snapshot.get('completeness_score', 0):.1%}
- Top coverage gaps: {json.dumps(coverage_snapshot.get('gap_ranges', [])[:5])}

Audit summary: {audit_report.get('summary', 'N/A')}

Respond with ONLY a JSON object:
{{
    "plan_type": "strategic",
    "priority_codes": ["P0xxx", "P0yyy"],
    "priority_ranges": ["P01xx-P01xx"],
    "reasoning": "brief explanation",
    "estimated_urls": 10
}}"""

    try:
        response = generate_completion(
            prompt,
            model=REASONING_MODEL,
            base_url=OLLAMA_BASE_URL,
            temperature=0.3,
            format_json=True,
        )

        plan = json.loads(response)
        return plan
    except (json.JSONDecodeError, Exception) as e:
        print(f"[planner] Failed to generate strategic plan: {e}")
        return None
