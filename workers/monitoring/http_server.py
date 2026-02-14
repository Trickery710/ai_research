"""HTTP server for exposing metrics to external monitoring systems (Prometheus, Grafana, etc.)."""

import sys
import json
import threading
from flask import Flask, jsonify

sys.path.insert(0, "/app")

from shared.redis_client import get_redis

app = Flask(__name__)


@app.route('/health')
def health():
    """Health check for the monitoring agent itself."""
    return jsonify({'status': 'running', 'service': 'monitor-agent'})


@app.route('/metrics')
def metrics():
    """Return latest metrics snapshot in JSON format."""
    try:
        redis_client = get_redis()
        latest = redis_client.get("metrics:latest")

        if latest:
            return jsonify(json.loads(latest))
        else:
            return jsonify({'error': 'No metrics available yet'}), 503
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/metrics/prometheus')
def prometheus_metrics():
    """Export metrics in Prometheus format."""
    try:
        redis_client = get_redis()
        latest = redis_client.get("metrics:latest")

        if not latest:
            return "# No metrics available\n", 503

        data = json.loads(latest)
        lines = []

        # Queue depths
        for queue, depth in data.get('queue_depths', {}).items():
            safe_name = queue.replace(':', '_').replace('-', '_')
            lines.append(f'refinery_queue_depth{{queue="{queue}"}} {depth}')

        # Processing stats
        for stage, stats in data.get('processing_stats', {}).items():
            lines.append(f'refinery_stage_total{{stage="{stage}"}} {stats.get("total", 0)}')
            lines.append(f'refinery_stage_failed{{stage="{stage}"}} {stats.get("failed", 0)}')

        # Container health (1 = healthy, 0 = unhealthy)
        for container, health in data.get('container_health', {}).items():
            value = 1 if health.get('status') == 'healthy' else 0
            lines.append(f'refinery_container_health{{container="{container}"}} {value}')

        # Document stats
        for stage, count in data.get('document_stats', {}).get('by_stage', {}).items():
            lines.append(f'refinery_documents_by_stage{{stage="{stage}"}} {count}')

        return '\n'.join(lines) + '\n', 200, {'Content-Type': 'text/plain'}
    except Exception as e:
        return f"# Error: {str(e)}\n", 500, {'Content-Type': 'text/plain'}


def start_metrics_server(port=8001):
    """Start Flask server in background thread."""
    def run():
        app.run(host='0.0.0.0', port=port, threaded=True, use_reloader=False)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    print(f"[monitor] Metrics server started on port {port}")
