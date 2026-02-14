"""Audit logging for all healing actions."""

import sys
from datetime import datetime

sys.path.insert(0, "/app")

from shared.db import execute_query


def log_healing_action(
    alert_id: str,
    action_type: str,
    component: str,
    decision: str,
    success: bool = None,
    result: str = None,
    llm_reasoning: str = None,
    reason: str = None
):
    """Log a healing action to the database for audit trail."""

    try:
        execute_query(
            """INSERT INTO research.healing_log
               (alert_id, action_type, component, decision, success, result, llm_reasoning, reason)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (alert_id, action_type, component, decision, success, result, llm_reasoning, reason)
        )

        print(f"[audit] {decision.upper()} - {action_type} on {component}")

    except Exception as e:
        # Log to stderr if DB logging fails (don't fail the healing action)
        print(f"[audit] ERROR: Failed to log healing action: {e}")
