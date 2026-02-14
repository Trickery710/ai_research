"""Healing Agent Worker.

Consumes alerts from the monitoring:alerts Redis queue, analyzes them using
the reasoning LLM (llama3 on llm-reason), generates fix strategies, and
executes approved actions. All healing actions are logged to the
research.healing_log table for audit trail and learning.

Safety-first design:
- Rate limiting: MAX_ACTIONS_PER_HOUR limit
- Cooldown period between actions
- Allow/deny lists for auto-fix
- Requires confirmation for destructive actions
- Idempotency checks to prevent duplicate fixes
"""

import sys
import os
import json
import time
import logging
from datetime import datetime

sys.path.insert(0, "/app")

from shared.redis_client import pop_job
from shared.db import execute_query

from analyzer import analyze_alert_with_llm
from executor import execute_healing_action
from safety import (
    is_action_allowed,
    check_rate_limits,
    check_idempotency,
    record_action
)
from audit_logger import log_healing_action

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [healing] %(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)


class HealingAgent:
    """Main healing orchestrator."""

    def __init__(self):
        self.alert_queue = os.environ.get("ALERT_QUEUE", "monitoring:alerts")
        self.auto_fix_enabled = os.environ.get("AUTO_FIX_ENABLED", "true").lower() == "true"
        self.cooldown = int(os.environ.get("COOLDOWN_BETWEEN_ACTIONS", 120))
        self.last_action_time = None

        logger.info(f"Healing agent initialized:")
        logger.info(f"  - Alert queue: {self.alert_queue}")
        logger.info(f"  - Auto-fix enabled: {self.auto_fix_enabled}")
        logger.info(f"  - Cooldown: {self.cooldown}s")
        logger.info(f"  - Allow list: {os.environ.get('AUTO_FIX_ALLOW', 'N/A')}")

    def process_alert(self, alert_json: str):
        """Process a single alert from the monitoring agent."""
        try:
            alert = json.loads(alert_json)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse alert JSON: {e}")
            return

        alert_id = alert.get('id', 'unknown')
        alert_type = alert.get('type', 'unknown')
        severity = alert.get('severity', 'unknown')
        component = alert.get('component', 'unknown')

        logger.info(f"Processing alert {alert_id}: {alert_type} ({severity}) on {component}")

        # Check idempotency: have we already processed this exact alert recently?
        if not check_idempotency(alert):
            logger.info(f"Alert {alert_id} already processed recently, skipping")
            return

        # Use LLM to analyze the alert and propose fix strategy
        logger.debug("Analyzing alert with LLM...")
        analysis = analyze_alert_with_llm(alert)

        if not analysis:
            logger.error(f"Failed to analyze alert {alert_id}")
            log_healing_action(
                alert_id=alert_id,
                action_type='analysis_failed',
                component=component,
                decision='skipped',
                reason='LLM analysis failed'
            )
            return

        proposed_action = analysis.get('action')
        confidence = analysis.get('confidence', 0.0)
        reasoning = analysis.get('reasoning', '')

        logger.info(f"LLM analysis: action={proposed_action}, confidence={confidence:.2f}")
        logger.debug(f"Reasoning: {reasoning}")

        # Safety checks
        if not is_action_allowed(proposed_action):
            logger.warning(f"Action '{proposed_action}' is not in allow list, escalating to human")
            log_healing_action(
                alert_id=alert_id,
                action_type=proposed_action,
                component=component,
                decision='escalated',
                reason='Action not auto-approved',
                llm_reasoning=reasoning
            )
            return

        if not check_rate_limits():
            logger.warning(f"Rate limit exceeded, deferring action")
            log_healing_action(
                alert_id=alert_id,
                action_type=proposed_action,
                component=component,
                decision='deferred',
                reason='Rate limit exceeded'
            )
            return

        # Cooldown check
        if self.last_action_time:
            time_since_last = (datetime.now() - self.last_action_time).total_seconds()
            if time_since_last < self.cooldown:
                wait_time = self.cooldown - time_since_last
                logger.info(f"Cooldown active, waiting {wait_time:.0f}s")
                time.sleep(wait_time)

        # Execute the healing action
        if self.auto_fix_enabled and confidence >= 0.7:
            logger.info(f"Executing auto-fix: {proposed_action}")

            success, result_message = execute_healing_action(proposed_action, alert, analysis)

            log_healing_action(
                alert_id=alert_id,
                action_type=proposed_action,
                component=component,
                decision='executed',
                success=success,
                result=result_message,
                llm_reasoning=reasoning
            )

            if success:
                logger.info(f"Healing action succeeded: {result_message}")
            else:
                logger.error(f"Healing action failed: {result_message}")

            self.last_action_time = datetime.now()
            record_action(proposed_action)

        else:
            reason = f"Low confidence ({confidence:.2f})" if confidence < 0.7 else "Auto-fix disabled"
            logger.info(f"Not executing: {reason}, escalating")
            log_healing_action(
                alert_id=alert_id,
                action_type=proposed_action,
                component=component,
                decision='escalated',
                reason=reason,
                llm_reasoning=reasoning
            )

    def run(self):
        """Main healing loop."""
        logger.info(f"Healing agent started, listening on {self.alert_queue}")

        while True:
            try:
                alert_json = pop_job(self.alert_queue, timeout=5)
                if alert_json:
                    self.process_alert(alert_json)
            except Exception as e:
                logger.error(f"Error processing alert: {e}", exc_info=True)

            time.sleep(0.5)


def ensure_healing_log_table():
    """Ensure healing_log table exists."""
    try:
        execute_query("""
            CREATE TABLE IF NOT EXISTS research.healing_log (
                id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                alert_id TEXT,
                action_type TEXT NOT NULL,
                component TEXT,
                decision TEXT NOT NULL,
                success BOOLEAN,
                result TEXT,
                llm_reasoning TEXT,
                reason TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """)

        execute_query("""
            CREATE INDEX IF NOT EXISTS idx_healing_log_created
            ON research.healing_log(created_at DESC)
        """)

        execute_query("""
            CREATE INDEX IF NOT EXISTS idx_healing_log_component
            ON research.healing_log(component, created_at DESC)
        """)

        logger.info("Healing log table verified/created")

    except Exception as e:
        logger.error(f"Failed to create healing_log table: {e}")


if __name__ == "__main__":
    # Ensure database schema is ready
    ensure_healing_log_table()

    # Start healing agent
    agent = HealingAgent()
    agent.run()
