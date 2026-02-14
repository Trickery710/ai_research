"""Monitors system resource usage via Redis queue depths."""
import os
from shared.redis_client import get_redis

MAX_GPU_QUEUE_ITEMS = int(os.environ.get("MAX_GPU_QUEUE_ITEMS", 20))
MAX_CONCURRENT_CRAWLS = int(os.environ.get("MAX_CONCURRENT_CRAWLS", 5))

# Queue name -> resource type mapping
GPU_QUEUES = ["jobs:evaluate", "jobs:extract", "jobs:embed"]
CRAWL_QUEUES = ["jobs:crawl", "jobs:chunk"]
ALL_QUEUES = [
    "jobs:crawl", "jobs:chunk", "jobs:embed",
    "jobs:evaluate", "jobs:extract", "jobs:resolve"
]


def get_queue_depths():
    """Get current depth of all pipeline queues.

    Returns:
        dict mapping queue name -> depth.
    """
    r = get_redis()
    return {q: r.llen(q) for q in ALL_QUEUES}


def get_resource_availability():
    """Assess whether GPU and crawl resources are available.

    Returns:
        dict with gpu_available, crawl_available, and detailed metrics.
    """
    depths = get_queue_depths()

    gpu_load = sum(depths.get(q, 0) for q in GPU_QUEUES)
    crawl_load = sum(depths.get(q, 0) for q in CRAWL_QUEUES)
    total_load = sum(depths.values())

    gpu_available = gpu_load < MAX_GPU_QUEUE_ITEMS
    crawl_available = crawl_load < MAX_CONCURRENT_CRAWLS

    return {
        "gpu_available": gpu_available,
        "crawl_available": crawl_available,
        "gpu_load": gpu_load,
        "gpu_max": MAX_GPU_QUEUE_ITEMS,
        "crawl_load": crawl_load,
        "crawl_max": MAX_CONCURRENT_CRAWLS,
        "total_queued": total_load,
        "queue_depths": depths,
        "pipeline_idle": total_load == 0,
    }


def is_pipeline_busy():
    """Quick check: is the pipeline under significant load?

    Returns:
        True if total queued items > half of GPU max.
    """
    depths = get_queue_depths()
    total = sum(depths.values())
    return total > (MAX_GPU_QUEUE_ITEMS // 2)


def get_system_state():
    """Get a complete system state snapshot for logging.

    Returns:
        dict with resources, queue depths, and timestamps.
    """
    resources = get_resource_availability()

    return {
        "resources": resources,
        "queue_depths": resources["queue_depths"],
        "gpu_available": resources["gpu_available"],
        "crawl_available": resources["crawl_available"],
        "pipeline_idle": resources["pipeline_idle"],
        "total_queued": resources["total_queued"],
    }
