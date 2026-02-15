#!/usr/bin/env bash
# Exports NVIDIA GPU metrics for node-exporter textfile collector.
# Install: crontab -e → */1 * * * * /path/to/nvidia-smi-collector.sh
#
# The output file must be in the node-exporter textfile directory.
# With the observatory docker-compose, that's the node_textfile volume.
# For host-level cron, write to the volume mount path instead.

set -euo pipefail

OUTPUT="/tmp/nvidia-smi-metrics.prom"
TEXTFILE_DIR="${TEXTFILE_DIR:-/tmp/node-exporter-textfile}"

mkdir -p "$TEXTFILE_DIR"

if ! command -v nvidia-smi &>/dev/null; then
    echo "# nvidia-smi not found" > "${TEXTFILE_DIR}/nvidia.prom"
    exit 0
fi

# Query GPU metrics: index, name, temp, power, mem_used, mem_total, utilization
nvidia-smi --query-gpu=index,name,temperature.gpu,power.draw,memory.used,memory.total,utilization.gpu \
    --format=csv,noheader,nounits 2>/dev/null | while IFS=', ' read -r idx name temp power mem_used mem_total util; do
    # Clean GPU name for label (remove spaces)
    name=$(echo "$name" | tr ' ' '_')

    cat <<EOF
nvidia_gpu_temperature_celsius{gpu="${idx}",name="${name}"} ${temp}
nvidia_gpu_power_watts{gpu="${idx}",name="${name}"} ${power}
nvidia_gpu_memory_used_bytes{gpu="${idx}",name="${name}"} $((mem_used * 1048576))
nvidia_gpu_memory_total_bytes{gpu="${idx}",name="${name}"} $((mem_total * 1048576))
nvidia_gpu_utilization_percent{gpu="${idx}",name="${name}"} ${util}
EOF
done > "$OUTPUT"

mv "$OUTPUT" "${TEXTFILE_DIR}/nvidia.prom"
