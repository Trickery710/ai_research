"""Redis client wrapper for job queue operations."""
import atexit
import logging
import redis
from shared.config import Config

logger = logging.getLogger(__name__)

_client = None


def get_redis():
    """Lazily initialize and return the Redis client."""
    global _client
    if _client is None:
        _client = redis.Redis(
            host=Config.REDIS_HOST,
            port=Config.REDIS_PORT,
            password=Config.REDIS_PASSWORD or None,
            decode_responses=True,
            socket_connect_timeout=10,
            socket_timeout=10,
            retry_on_timeout=True,
        )
        # Safety-net atexit handler in case graceful.cleanup() is not called.
        atexit.register(close_redis)
    return _client


def close_redis():
    """Close the Redis connection and reset the global reference.

    Safe to call multiple times (idempotent).
    """
    global _client
    if _client is not None:
        try:
            _client.close()
            logger.info("Redis connection closed.")
        except Exception as e:
            logger.warning(f"Error closing Redis connection: {e}")
        finally:
            _client = None


def pop_job(queue_name, timeout=5):
    """Blocking pop from a Redis list (FIFO via BRPOP).

    Args:
        queue_name: The Redis key for the list.
        timeout: Seconds to block waiting for a job.

    Returns:
        The job payload string, or None if timeout expired.
    """
    try:
        result = get_redis().brpop(queue_name, timeout=timeout)
        if result:
            return result[1]  # brpop returns (key, value) tuple
    except redis.exceptions.ConnectionError as e:
        logger.warning(f"Redis connection error in pop_job: {e}")
        # Reset client so the next call creates a fresh connection
        global _client
        _client = None
        return None
    return None


def push_job(queue_name, job_data):
    """Push a job onto a Redis list (LPUSH for FIFO with BRPOP)."""
    get_redis().lpush(queue_name, job_data)


def get_queue_length(queue_name):
    """Return the number of items in a queue."""
    return get_redis().llen(queue_name)
