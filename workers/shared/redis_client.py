"""Redis client wrapper for job queue operations."""
import redis
from shared.config import Config

_client = None


def get_redis():
    """Lazily initialize and return the Redis client."""
    global _client
    if _client is None:
        _client = redis.Redis(
            host=Config.REDIS_HOST,
            port=Config.REDIS_PORT,
            decode_responses=True
        )
    return _client


def pop_job(queue_name, timeout=5):
    """Blocking pop from a Redis list (FIFO via BRPOP).

    Args:
        queue_name: The Redis key for the list.
        timeout: Seconds to block waiting for a job.

    Returns:
        The job payload string, or None if timeout expired.
    """
    result = get_redis().brpop(queue_name, timeout=timeout)
    if result:
        return result[1]  # brpop returns (key, value) tuple
    return None


def push_job(queue_name, job_data):
    """Push a job onto a Redis list (LPUSH for FIFO with BRPOP)."""
    get_redis().lpush(queue_name, job_data)


def get_queue_length(queue_name):
    """Return the number of items in a queue."""
    return get_redis().llen(queue_name)
