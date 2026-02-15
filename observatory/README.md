# Observatory - Prometheus + Grafana Monitoring

Monitoring stack for the Refinery pipeline. Runs alongside the main stack on the P340 server.

## Quick Start

```bash
# Make sure the refinery stack is running first (creates the 'refinery' network)
cd observatory
docker compose up -d
```

## Access

- **Grafana**: `http://<P340_IP>:3000` (login: admin / admin)
- **Prometheus**: `http://localhost:9090` (localhost-only for security)

Three dashboards are auto-provisioned in the "Refinery" folder:
- **Stack Health** - Queue depths, throughput, error rates, container health
- **Database** - Table sizes, row counts, connections, cache hit ratio
- **Server Resources** - CPU, memory, disk, network, GPU (optional)

## GPU Metrics (Optional)

To get GPU metrics in the Server Resources dashboard:

```bash
chmod +x nvidia-smi-collector.sh

# Find the node_textfile volume mount
docker volume inspect observatory_node_textfile

# Set TEXTFILE_DIR to that mount path and run via cron
# Example: every minute
(crontab -l 2>/dev/null; echo "* * * * * TEXTFILE_DIR=/var/lib/docker/volumes/observatory_node_textfile/_data /path/to/nvidia-smi-collector.sh") | crontab -
```

## Architecture

```
observatory/docker-compose.yml
 ├─ prometheus     → scrapes all metric sources (port 9090, localhost)
 ├─ postgres-exporter → DB metrics from refinery_postgres (port 9187)
 ├─ node-exporter  → system metrics: CPU, RAM, disk, network (port 9100)
 └─ grafana        → dashboards (port 3000, exposed for remote access)
```

All services join the existing `refinery` network to reach monitor-agent and postgres.

## Verification

1. Check Prometheus targets: `http://localhost:9090/targets` — all 3 should show UP
2. Open Grafana: `http://<P340_IP>:3000` → "Refinery" folder → 3 dashboards
3. Stack Health should show queue depths and container status immediately

## Adding Custom Dashboards

Place `.json` dashboard files in `grafana/dashboards/`. They'll be picked up automatically on next Grafana restart.

## Stopping

```bash
docker compose down        # stop services, keep data
docker compose down -v     # stop and delete all stored metrics/dashboards
```
