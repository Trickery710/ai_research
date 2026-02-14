"""Safety mechanisms to prevent runaway healing."""

import sys
import os
import hashlib
from typing import Dict

sys.path.insert(0, "/app")

from shared.redis_client import get_redis


def is_action_allowed(action: str) -> bool:
    """Check if an action is in the allow list and not in deny list."""
    allow_list = os.environ.get("AUTO_FIX_ALLOW", "restart_worker,requeue_documents,clear_stale_locks").split(',')
    deny_list = os.environ.get("AUTO_FIX_DENY", "restart_container,database_operations,delete_data").split(',')

    action_type = action.split(':')[0] if ':' in action else action

    # Deny list takes precedence
    if action_type in deny_list:
        return False

    # Must be in allow list
    return action_type in allow_list


def check_rate_limits() -> bool:
    """Check if we've exceeded MAX_ACTIONS_PER_HOUR."""
    max_actions = int(os.environ.get("MAX_ACTIONS_PER_HOUR", 10))

    redis_client = get_redis()
    key = "healing:action_count"

    # Get current count
    count = redis_client.get(key)
    if count is None:
        count = 0
    else:
        count = int(count)

    if count >= max_actions:
        return False

    return True


def record_action(action: str):
    """Increment action counter with 1-hour TTL."""
    redis_client = get_redis()
    key = "healing:action_count"

    # Increment and set TTL
    pipe = redis_client.pipeline()
    pipe.incr(key)
    pipe.expire(key, 3600)  # 1 hour TTL
    pipe.execute()


def check_idempotency(alert: Dict) -> bool:
    """Check if we've already processed this exact alert recently."""
    # Create a fingerprint of the alert
    fingerprint = _create_alert_fingerprint(alert)

    redis_client = get_redis()
    key = f"healing:processed:{fingerprint}"

    # Check if this fingerprint exists
    if redis_client.exists(key):
        return False  # Already processed

    # Mark as processed with 10-minute TTL
    redis_client.setex(key, 600, "1")
    return True


def _create_alert_fingerprint(alert: Dict) -> str:
    """Create a hash fingerprint of an alert for deduplication."""
    # Use type + component + details to identify duplicate alerts
    key_parts = [
        alert.get('type', ''),
        alert.get('component', ''),
        alert.get('details', '')[:100]  # First 100 chars of details
    ]

    fingerprint_str = '|'.join(key_parts)
    return hashlib.md5(fingerprint_str.encode()).hexdigest()
