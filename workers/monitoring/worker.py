"""Monitoring Agent Worker.

Continuously monitors the health of all services in the AI Research Refinery:
- Container health status (via HTTP endpoints)
- Queue depths and movement (Redis)
- Processing pipeline metrics (PostgreSQL)
- Error rates and patterns (processing_log table)
- LLM service availability (Ollama endpoints)

Detected anomalies are formatted as structured reports and pushed to
the monitoring:alerts Redis queue for consumption by the healing agent.

Runs every 45-60 seconds (configurable via MONITOR_INTERVAL).
"""

import sys
import os
import json
import time
import logging
from datetime import datetime

sys.path.insert(0, "/app")

from shared.redis_client import get_redis

from detectors import (
    detect_stalled_queues,
    detect_error_rate_spikes,
    detect_processing_time_anomalies,
    detect_unhealthy_containers,
    detect_stuck_documents
)
from metrics_collector import collect_all_metrics
from http_server import start_metrics_server

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [monitor] %(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)


class MonitoringAgent:
    """Main monitoring orchestrator."""

    def __init__(self):
        self.interval = int(os.environ.get("MONITOR_INTERVAL", "45"))
        self.alert_queue = os.environ.get("ALERT_QUEUE", "monitoring:alerts")
        self.metrics_retention = int(os.environ.get("MONITOR_METRICS_RETENTION", "86400"))
        self.last_queue_depths = {}  # Track queue movement
        self.last_check_time = None

        logger.info(f"Monitoring agent initialized:")
        logger.info(f"  - Interval: {self.interval}s")
        logger.info(f"  - Alert queue: {self.alert_queue}")
        logger.info(f"  - Metrics retention: {self.metrics_retention}s")

    def run_monitoring_cycle(self):
        """Execute one complete monitoring cycle."""
        cycle_start = time.time()

        try:
            # Collect current state metrics
            logger.debug("Collecting metrics...")
            metrics = collect_all_metrics()

            # Store metrics in Redis with timestamp (for trends)
            self._store_metrics(metrics)

            # Run all anomaly detectors
            alerts = []

            alerts.extend(detect_stalled_queues(
                metrics['queue_depths'],
                self.last_queue_depths,
                self.last_check_time
            ))

            alerts.extend(detect_error_rate_spikes(metrics['processing_stats']))

            alerts.extend(detect_processing_time_anomalies(metrics['stage_timings']))

            alerts.extend(detect_unhealthy_containers(metrics['container_health']))

            alerts.extend(detect_stuck_documents(metrics['document_stats']))

            # Send alerts to healing agent (or log if no healing agent)
            for alert in alerts:
                self._send_alert(alert)

            # Update state for next cycle
            self.last_queue_depths = metrics['queue_depths'].copy()
            self.last_check_time = datetime.now()

            cycle_duration = time.time() - cycle_start
            logger.info(f"Monitoring cycle completed in {cycle_duration:.2f}s, "
                       f"{len(alerts)} alerts generated")

            # Log summary of current state
            self._log_summary(metrics, alerts)

        except Exception as e:
            logger.error(f"Monitoring cycle failed: {e}", exc_info=True)

    def _store_metrics(self, metrics: dict):
        """Store metrics in Redis with timestamp for trend analysis."""
        try:
            redis_client = get_redis()
            timestamp = int(time.time())
            key = f"metrics:snapshot:{timestamp}"

            redis_client.setex(
                key,
                self.metrics_retention,
                json.dumps(metrics, default=str)  # default=str for datetime serialization
            )

            # Also update "latest" key for quick access
            redis_client.set("metrics:latest", json.dumps(metrics, default=str))
            logger.debug(f"Stored metrics snapshot: {key}")

        except Exception as e:
            logger.error(f"Failed to store metrics: {e}")

    def _send_alert(self, alert: dict):
        """Push alert to healing agent queue."""
        try:
            alert['timestamp'] = datetime.now().isoformat()
            alert['id'] = f"alert_{int(time.time() * 1000)}"

            redis_client = get_redis()
            redis_client.lpush(self.alert_queue, json.dumps(alert))

            logger.warning(f"Alert sent: {alert['type']} - {alert['severity']} - {alert.get('component', 'unknown')}")
            logger.debug(f"Alert details: {alert['details']}")

        except Exception as e:
            logger.error(f"Failed to send alert: {e}")

    def _log_summary(self, metrics: dict, alerts: list):
        """Log a summary of current system state."""
        queue_depths = metrics.get('queue_depths', {})
        total_queued = sum(queue_depths.values())

        doc_stats = metrics.get('document_stats', {}).get('by_stage', {})
        total_docs = sum(doc_stats.values())

        backend_status = metrics.get('backend_health', {}).get('status', 'unknown')

        logger.info(f"System summary: {total_docs} docs, {total_queued} queued, "
                   f"backend: {backend_status}, {len(alerts)} alerts")

        # Log individual queue depths if any have items
        if total_queued > 0:
            queue_summary = ", ".join([f"{k.split(':')[1]}: {v}" for k, v in queue_depths.items() if v > 0])
            logger.debug(f"Active queues: {queue_summary}")

    def run(self):
        """Main monitoring loop."""
        from shared.graceful import GracefulShutdown, wait_for_db, wait_for_redis

        self._shutdown = GracefulShutdown()

        logger.info("Monitor agent started, starting metrics server...")

        wait_for_db()
        wait_for_redis()

        # Start HTTP metrics server in background thread
        start_metrics_server(port=8001)

        logger.info(f"Entering monitoring loop (interval={self.interval}s)")

        while self._shutdown.is_running():
            try:
                self.run_monitoring_cycle()
            except Exception as e:
                logger.error(f"Unexpected error in monitoring loop: {e}", exc_info=True)

            # Sleep in 1s increments to allow fast shutdown
            for _ in range(self.interval):
                if not self._shutdown.is_running():
                    break
                time.sleep(1)

        self._shutdown.cleanup()


if __name__ == "__main__":
    agent = MonitoringAgent()
    agent.run()
