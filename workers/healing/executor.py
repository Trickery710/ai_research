"""Execute healing actions safely."""

import sys
import subprocess
from typing import Tuple, Dict

sys.path.insert(0, "/app")

from shared.redis_client import get_redis
from shared.db import execute_query


def execute_healing_action(action: str, alert: Dict, analysis: Dict) -> Tuple[bool, str]:
    """Execute a healing action and return (success, message)."""

    action_type = action.split(':')[0] if ':' in action else action
    action_param = action.split(':', 1)[1] if ':' in action else None

    handlers = {
        'restart_worker': restart_worker,
        'restart_container': restart_container,
        'requeue_documents': requeue_documents,
        'requeue_errors': requeue_error_documents,
        'clear_stale_locks': clear_stale_locks,
        'escalate_to_human': escalate_to_human
    }

    handler = handlers.get(action_type)
    if not handler:
        return False, f"Unknown action type: {action_type}"

    try:
        return handler(action_param, alert, analysis)
    except Exception as e:
        return False, f"Action execution failed: {str(e)}"


def restart_worker(worker_name: str, alert: Dict, analysis: Dict) -> Tuple[bool, str]:
    """Restart a worker container using Docker."""
    if not worker_name:
        return False, "Worker name not specified"

    container_name = f"refinery_worker_{worker_name}"

    try:
        # Use docker restart command
        result = subprocess.run(
            ['docker', 'restart', container_name],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode == 0:
            return True, f"Successfully restarted {container_name}"
        else:
            return False, f"Docker restart failed: {result.stderr}"

    except subprocess.TimeoutExpired:
        return False, f"Docker restart timed out for {container_name}"
    except Exception as e:
        return False, f"Failed to restart {container_name}: {str(e)}"


def restart_container(container_name: str, alert: Dict, analysis: Dict) -> Tuple[bool, str]:
    """Restart any container (more generic than restart_worker)."""
    if not container_name:
        return False, "Container name not specified"

    full_name = f"refinery_{container_name}" if not container_name.startswith('refinery_') else container_name

    try:
        result = subprocess.run(
            ['docker', 'restart', full_name],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode == 0:
            return True, f"Successfully restarted {full_name}"
        else:
            return False, f"Docker restart failed: {result.stderr}"

    except Exception as e:
        return False, f"Failed to restart {full_name}: {str(e)}"


def requeue_documents(stage: str, alert: Dict, analysis: Dict) -> Tuple[bool, str]:
    """Re-queue stuck documents from a specific stage."""
    if not stage:
        return False, "Stage not specified"

    # Map stage to queue name
    stage_to_queue = {
        'chunking': 'jobs:chunk',
        'embedding': 'jobs:embed',
        'evaluating': 'jobs:evaluate',
        'extracting': 'jobs:extract',
        'resolving': 'jobs:resolve',
        'crawling': 'jobs:crawl'
    }

    queue_name = stage_to_queue.get(stage)
    if not queue_name:
        return False, f"Unknown stage: {stage}"

    try:
        # Find stuck documents in this stage
        rows = execute_query(
            """SELECT id FROM research.documents
               WHERE processing_stage = %s
               ORDER BY updated_at ASC
               LIMIT 100""",
            (stage,),
            fetch=True
        )

        if not rows:
            return True, f"No documents stuck in {stage} stage"

        # Push them back to the queue
        redis_client = get_redis()
        count = 0
        for row in rows:
            doc_id = str(row[0])
            redis_client.lpush(queue_name, doc_id)
            count += 1

        return True, f"Re-queued {count} documents to {queue_name}"

    except Exception as e:
        return False, f"Failed to requeue documents: {str(e)}"


def requeue_error_documents(target_stage: str, alert: Dict, analysis: Dict) -> Tuple[bool, str]:
    """Re-queue documents in 'error' state back to a target processing stage.

    The target_stage parameter determines which queue to push them to.
    Documents are reset from 'error' back to the target stage so the
    pipeline can retry them.
    """
    if not target_stage:
        target_stage = 'extracting'  # Most errors occur at extraction

    stage_to_queue = {
        'chunking': 'jobs:chunk',
        'embedding': 'jobs:embed',
        'evaluating': 'jobs:evaluate',
        'extracting': 'jobs:extract',
        'resolving': 'jobs:resolve',
        'crawling': 'jobs:crawl'
    }

    queue_name = stage_to_queue.get(target_stage)
    if not queue_name:
        return False, f"Unknown target stage: {target_stage}"

    try:
        rows = execute_query(
            """SELECT id FROM research.documents
               WHERE processing_stage = 'error'
               ORDER BY updated_at ASC
               LIMIT 200""",
            fetch=True
        )

        if not rows:
            return True, "No documents in error state"

        redis_client = get_redis()
        count = 0
        for row in rows:
            doc_id = str(row[0])
            # Reset stage so the worker picks it up cleanly
            execute_query(
                """UPDATE research.documents
                   SET processing_stage = %s, error_message = NULL, updated_at = NOW()
                   WHERE id = %s""",
                (target_stage, doc_id)
            )
            redis_client.lpush(queue_name, doc_id)
            count += 1

        return True, f"Re-queued {count} error documents to {queue_name}"

    except Exception as e:
        return False, f"Failed to requeue error documents: {str(e)}"


def clear_stale_locks(param: str, alert: Dict, analysis: Dict) -> Tuple[bool, str]:
    """Clear Redis locks older than 1 hour (for distributed lock issues)."""

    redis_client = get_redis()

    # Pattern for lock keys (adjust based on actual implementation)
    lock_pattern = "lock:*"

    try:
        # Scan for lock keys
        cursor = 0
        deleted_count = 0

        while True:
            cursor, keys = redis_client.scan(cursor, match=lock_pattern, count=100)

            for key in keys:
                # Check TTL - if > 3600 seconds or no TTL, consider stale
                ttl = redis_client.ttl(key)
                if ttl > 3600 or ttl == -1:  # -1 means no expiry
                    redis_client.delete(key)
                    deleted_count += 1

            if cursor == 0:
                break

        return True, f"Cleared {deleted_count} stale locks"

    except Exception as e:
        return False, f"Failed to clear locks: {str(e)}"


def escalate_to_human(param: str, alert: Dict, analysis: Dict) -> Tuple[bool, str]:
    """Log the alert for human review (no auto-fix)."""
    # In production, this would send a notification (Slack, PagerDuty, email, etc.)

    message = f"ESCALATED: {alert.get('type')} on {alert.get('component')} - {alert.get('details')}"
    print(f"[escalation] {message}")

    # Store in database for dashboard visibility
    try:
        execute_query(
            """INSERT INTO research.healing_log
               (alert_id, action_type, component, decision, reason, llm_reasoning)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (alert.get('id'), 'escalate_to_human', alert.get('component'),
             'escalated', f"Human review required: {analysis.get('reasoning')}",
             analysis.get('reasoning'))
        )
    except Exception as e:
        print(f"[escalation] Failed to log escalation: {e}")

    return True, "Alert escalated to human operator"
