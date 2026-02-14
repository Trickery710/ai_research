"""Anomaly detection functions.

Each function analyzes a specific aspect of system health and returns
a list of alert dictionaries. Alerts include:
- type: category of issue (stalled_queue, error_spike, etc.)
- severity: low, medium, high, critical
- component: affected service/stage
- details: specific information about the anomaly
- recommended_action: suggested fix (used by healing agent)
"""

import sys
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional

sys.path.insert(0, "/app")

# Thresholds from environment
QUEUE_STALL_THRESHOLD = int(os.environ.get("QUEUE_STALL_THRESHOLD", "300"))
ERROR_RATE_THRESHOLD = float(os.environ.get("ERROR_RATE_THRESHOLD", "0.15"))
PROCESSING_TIME_MULTIPLIER = float(os.environ.get("PROCESSING_TIME_THRESHOLD_MULTIPLIER", "3"))


def detect_stalled_queues(
    current_depths: Dict[str, int],
    previous_depths: Dict[str, int],
    last_check_time: Optional[datetime]
) -> List[Dict]:
    """Detect queues that have items but haven't moved in QUEUE_STALL_THRESHOLD seconds."""
    alerts = []

    if not previous_depths or not last_check_time:
        return alerts  # First run, no baseline

    time_since_last_check = (datetime.now() - last_check_time).total_seconds()

    if time_since_last_check < QUEUE_STALL_THRESHOLD:
        return alerts  # Not enough time to detect stall

    for queue_name, depth in current_depths.items():
        if depth == 0:
            continue  # Empty queue is fine

        prev_depth = previous_depths.get(queue_name, 0)

        # Queue has items but hasn't changed
        if depth > 0 and depth == prev_depth:
            worker_name = queue_name.split(':')[1] if ':' in queue_name else queue_name

            alerts.append({
                'type': 'stalled_queue',
                'severity': 'high' if depth > 10 else 'medium',
                'component': f'worker-{worker_name}',
                'queue': queue_name,
                'details': f"Queue '{queue_name}' has {depth} items but hasn't moved in {int(time_since_last_check)}s",
                'recommended_action': f'restart_worker:{worker_name}'
            })

    return alerts


def detect_error_rate_spikes(processing_stats: Dict) -> List[Dict]:
    """Detect stages with error rates above ERROR_RATE_THRESHOLD."""
    alerts = []

    for stage, stats in processing_stats.items():
        total = stats.get('total', 0)
        failed = stats.get('failed', 0)

        if total < 5:
            continue  # Too few samples

        error_rate = failed / total if total > 0 else 0

        if error_rate > ERROR_RATE_THRESHOLD:
            alerts.append({
                'type': 'error_rate_spike',
                'severity': 'critical' if error_rate > 0.5 else 'high',
                'component': f'worker-{stage}',
                'stage': stage,
                'details': f"Stage '{stage}' has {error_rate:.1%} error rate ({failed}/{total})",
                'error_rate': error_rate,
                'recommended_action': f'analyze_errors:{stage}'
            })

    return alerts


def detect_processing_time_anomalies(stage_timings: Dict) -> List[Dict]:
    """Detect stages taking significantly longer than average."""
    alerts = []

    for stage, timing_data in stage_timings.items():
        recent_avg = timing_data.get('recent_avg_ms', 0)
        historical_avg = timing_data.get('historical_avg_ms', 0)

        if historical_avg == 0 or recent_avg == 0:
            continue  # No baseline yet

        if recent_avg > historical_avg * PROCESSING_TIME_MULTIPLIER:
            slowdown_factor = recent_avg / historical_avg

            alerts.append({
                'type': 'processing_slowdown',
                'severity': 'medium',
                'component': f'worker-{stage}',
                'stage': stage,
                'details': f"Stage '{stage}' is {slowdown_factor:.1f}x slower than normal "
                          f"({recent_avg:.0f}ms vs {historical_avg:.0f}ms avg)",
                'recommended_action': f'check_resource_usage:{stage}'
            })

    return alerts


def detect_unhealthy_containers(container_health: Dict) -> List[Dict]:
    """Detect containers reporting unhealthy status."""
    alerts = []

    grace_period = int(os.environ.get("UNHEALTHY_CONTAINER_GRACE_PERIOD", "60"))

    for container_name, health_data in container_health.items():
        status = health_data.get('status')
        unhealthy_since = health_data.get('unhealthy_since')

        if status == 'unhealthy':
            # Check if it's been unhealthy longer than grace period
            if unhealthy_since and (datetime.now() - unhealthy_since).total_seconds() > grace_period:
                alerts.append({
                    'type': 'unhealthy_container',
                    'severity': 'critical',
                    'component': container_name,
                    'details': f"Container '{container_name}' has been unhealthy for "
                              f"{int((datetime.now() - unhealthy_since).total_seconds())}s",
                    'recommended_action': f'restart_container:{container_name}'
                })

        elif status == 'starting':
            # Container stuck in starting state
            if unhealthy_since and (datetime.now() - unhealthy_since).total_seconds() > 120:
                alerts.append({
                    'type': 'stuck_container',
                    'severity': 'high',
                    'component': container_name,
                    'details': f"Container '{container_name}' stuck in 'starting' state for "
                              f"{int((datetime.now() - unhealthy_since).total_seconds())}s",
                    'recommended_action': f'restart_container:{container_name}'
                })

    return alerts


def detect_stuck_documents(document_stats: Dict) -> List[Dict]:
    """Detect documents stuck in processing stages for too long."""
    alerts = []

    stuck_threshold_minutes = 30

    for stage, docs in document_stats.get('stuck_documents', {}).items():
        if len(docs) > 0:
            alerts.append({
                'type': 'stuck_documents',
                'severity': 'medium',
                'component': f'stage-{stage}',
                'stage': stage,
                'details': f"{len(docs)} document(s) stuck in '{stage}' stage for >{stuck_threshold_minutes}min",
                'document_ids': docs[:5],  # Include first 5 IDs
                'recommended_action': f'requeue_documents:{stage}'
            })

    return alerts
