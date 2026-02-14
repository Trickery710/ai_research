"""CRUD operations for orchestrator_tasks table."""
import json
from shared.db import execute_query, execute_query_one


# Task status constants
STATUS_PENDING = "pending"
STATUS_IN_PROGRESS = "in_progress"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"

# Task type constants
TASK_RESEARCH = "research"
TASK_AUDIT = "audit"
TASK_REPROCESS = "reprocess"
TASK_COVERAGE = "coverage_expansion"


def create_task(task_type, priority, payload=None, assigned_to=None,
                scheduled_after=None):
    """Create a new orchestrator task.

    Args:
        task_type: Type of task (research, audit, reprocess, etc.).
        priority: Priority 1-6 (lower = higher priority).
        payload: Optional dict with task parameters.
        assigned_to: Optional worker assignment.
        scheduled_after: Optional timestamp string to delay execution.

    Returns:
        UUID string of created task, or None on failure.
    """
    row = execute_query_one(
        """INSERT INTO research.orchestrator_tasks
           (task_type, priority, payload, assigned_to, scheduled_after)
           VALUES (%s, %s, %s, %s, %s)
           RETURNING id""",
        (
            task_type,
            priority,
            json.dumps(payload) if payload else "{}",
            assigned_to,
            scheduled_after,
        )
    )
    return str(row[0]) if row else None


def get_pending_tasks(limit=20):
    """Get pending tasks ordered by priority, then creation time.

    Returns:
        List of task tuples.
    """
    rows = execute_query(
        """SELECT id, task_type, status, priority, payload, assigned_to,
                  retry_count, scheduled_after, created_at
        FROM research.orchestrator_tasks
        WHERE status = 'pending'
            AND (scheduled_after IS NULL OR scheduled_after <= NOW())
        ORDER BY priority ASC, created_at ASC
        LIMIT %s""",
        (limit,),
        fetch=True
    )
    return rows or []


def get_active_tasks():
    """Get all currently in-progress tasks.

    Returns:
        List of task tuples.
    """
    rows = execute_query(
        """SELECT id, task_type, status, priority, payload, assigned_to,
                  started_at
        FROM research.orchestrator_tasks
        WHERE status = 'in_progress'
        ORDER BY started_at ASC""",
        fetch=True
    )
    return rows or []


def start_task(task_id):
    """Mark a task as in_progress."""
    execute_query(
        """UPDATE research.orchestrator_tasks
           SET status = 'in_progress', started_at = NOW()
           WHERE id = %s""",
        (task_id,)
    )


def complete_task(task_id, result=None):
    """Mark a task as completed with optional result.

    Args:
        task_id: Task UUID string.
        result: Optional dict with task results.
    """
    execute_query(
        """UPDATE research.orchestrator_tasks
           SET status = 'completed', completed_at = NOW(),
               result = %s
           WHERE id = %s""",
        (json.dumps(result) if result else None, task_id)
    )


def fail_task(task_id, error_message):
    """Mark a task as failed.

    Increments retry_count. If retry_count < 3, resets to pending.
    """
    execute_query(
        """UPDATE research.orchestrator_tasks
           SET status = CASE WHEN retry_count < 3 THEN 'pending' ELSE 'failed' END,
               error_message = %s,
               retry_count = retry_count + 1
           WHERE id = %s""",
        (error_message[:500], task_id)
    )


def cancel_task(task_id):
    """Cancel a pending task."""
    execute_query(
        """UPDATE research.orchestrator_tasks
           SET status = 'cancelled'
           WHERE id = %s AND status = 'pending'""",
        (task_id,)
    )


def get_task_counts():
    """Get task counts by status.

    Returns:
        dict with status -> count mapping.
    """
    rows = execute_query(
        """SELECT status, COUNT(*) AS count
        FROM research.orchestrator_tasks
        GROUP BY status""",
        fetch=True
    )
    return {row[0]: row[1] for row in (rows or [])}


def has_pending_task_of_type(task_type, payload_match=None):
    """Check if a pending/in_progress task of this type already exists.

    Prevents duplicate task creation.

    Args:
        task_type: Task type string.
        payload_match: Optional dict - if provided, checks payload contains these keys.

    Returns:
        True if matching task exists.
    """
    row = execute_query_one(
        """SELECT COUNT(*) FROM research.orchestrator_tasks
        WHERE task_type = %s AND status IN ('pending', 'in_progress')""",
        (task_type,)
    )
    return row[0] > 0 if row else False


def cleanup_old_tasks(days=7):
    """Delete completed/cancelled tasks older than N days."""
    execute_query(
        """DELETE FROM research.orchestrator_tasks
        WHERE status IN ('completed', 'cancelled', 'failed')
            AND completed_at < NOW() - INTERVAL '%s days'""",
        (days,)
    )
