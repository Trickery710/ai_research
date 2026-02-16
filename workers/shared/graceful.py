"""Graceful shutdown handler for all workers.

Registers SIGTERM and SIGINT handlers that flip a shared flag,
allowing worker main loops to exit cleanly, close DB pools, and
disconnect from Redis before the container is killed.

Usage in any worker:

    from shared.graceful import GracefulShutdown, shutdown_handler

    shutdown = GracefulShutdown()

    def main():
        while shutdown.is_running():
            job = pop_job(queue, timeout=5)
            if job:
                process(job)

        # Clean up on exit
        shutdown.cleanup()

Or use the convenience decorator for simple workers:

    @shutdown_handler
    def main(shutdown):
        while shutdown.is_running():
            ...
"""
import signal
import logging
import threading

logger = logging.getLogger(__name__)

# Module-level singleton so all imports share the same state
_instance = None
_lock = threading.Lock()


class GracefulShutdown:
    """Manages graceful shutdown state and cleanup for a worker process.

    Only one instance is created per process (singleton pattern).
    Registering signals is done automatically on first instantiation.
    """

    def __new__(cls):
        global _instance
        if _instance is None:
            with _lock:
                if _instance is None:
                    _instance = super().__new__(cls)
                    _instance._initialized = False
        return _instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._running = True
        self._cleanup_callbacks = []
        self._register_signals()
        logger.info("Graceful shutdown handler registered (SIGTERM, SIGINT)")

    def _register_signals(self):
        """Register signal handlers for SIGTERM and SIGINT."""
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

    def _handle_signal(self, signum, frame):
        """Signal callback -- sets the running flag to False."""
        sig_name = signal.Signals(signum).name
        logger.info(f"Received {sig_name} (signal {signum}), initiating graceful shutdown...")
        print(f"[shutdown] Received {sig_name}, shutting down gracefully...")
        self._running = False

    def is_running(self):
        """Return True while the worker should keep running."""
        return self._running

    def register_cleanup(self, callback):
        """Register a cleanup function to run on shutdown.

        Callbacks are called in LIFO order (last registered = first called).

        Args:
            callback: A callable with no arguments.
        """
        self._cleanup_callbacks.append(callback)

    def cleanup(self):
        """Run all registered cleanup callbacks, then close shared resources.

        This method is idempotent -- calling it multiple times is safe.
        """
        # Run user-registered callbacks in reverse order
        while self._cleanup_callbacks:
            cb = self._cleanup_callbacks.pop()
            try:
                cb()
            except Exception as e:
                logger.warning(f"Cleanup callback {cb.__name__} failed: {e}")

        # Always close shared DB pool and Redis connection
        _close_db_pool()
        _close_redis()

        logger.info("Graceful shutdown complete.")
        print("[shutdown] Cleanup complete, exiting.")


def _close_db_pool():
    """Close the shared PostgreSQL connection pool if it exists."""
    try:
        from shared import db
        if db._pool is not None:
            logger.info("Closing PostgreSQL connection pool...")
            db._pool.closeall()
            db._pool = None
            logger.info("PostgreSQL connection pool closed.")
    except Exception as e:
        logger.warning(f"Error closing DB pool: {e}")


def _close_redis():
    """Close the shared Redis client if it exists."""
    try:
        from shared import redis_client
        if redis_client._client is not None:
            logger.info("Closing Redis connection...")
            redis_client._client.close()
            redis_client._client = None
            logger.info("Redis connection closed.")
    except Exception as e:
        logger.warning(f"Error closing Redis client: {e}")


def shutdown_handler(main_func):
    """Decorator that injects a GracefulShutdown instance and handles cleanup.

    Example::

        @shutdown_handler
        def main(shutdown):
            while shutdown.is_running():
                ...

    The decorated function is called with the shutdown instance, and
    cleanup() is called automatically when main() returns.
    """
    def wrapper(*args, **kwargs):
        shutdown = GracefulShutdown()
        try:
            return main_func(shutdown, *args, **kwargs)
        finally:
            shutdown.cleanup()
    wrapper.__name__ = main_func.__name__
    wrapper.__doc__ = main_func.__doc__
    return wrapper


def wait_for_db(max_retries=30, retry_delay=2):
    """Block until the database is reachable, or raise after max_retries.

    This should be called at worker startup before entering the main loop,
    so that workers don't crash-loop while Postgres is still starting.

    Args:
        max_retries: Maximum number of connection attempts.
        retry_delay: Seconds between retries.

    Raises:
        ConnectionError: If the database is still unreachable after all retries.
    """
    import time

    for attempt in range(1, max_retries + 1):
        try:
            from shared.db import get_connection, return_connection
            conn = get_connection(max_retries=1, retry_delay=0)
            return_connection(conn)
            logger.info(f"Database ready (attempt {attempt}/{max_retries})")
            return
        except Exception as e:
            if attempt < max_retries:
                logger.warning(
                    f"Database not ready (attempt {attempt}/{max_retries}): {e}"
                )
                time.sleep(retry_delay)
            else:
                raise ConnectionError(
                    f"Database not reachable after {max_retries} attempts: {e}"
                ) from e


def wait_for_redis(max_retries=30, retry_delay=2):
    """Block until Redis is reachable, or raise after max_retries.

    Args:
        max_retries: Maximum number of ping attempts.
        retry_delay: Seconds between retries.

    Raises:
        ConnectionError: If Redis is still unreachable after all retries.
    """
    import time

    for attempt in range(1, max_retries + 1):
        try:
            from shared.redis_client import get_redis
            client = get_redis()
            client.ping()
            logger.info(f"Redis ready (attempt {attempt}/{max_retries})")
            return
        except Exception as e:
            if attempt < max_retries:
                logger.warning(
                    f"Redis not ready (attempt {attempt}/{max_retries}): {e}"
                )
                time.sleep(retry_delay)
            else:
                raise ConnectionError(
                    f"Redis not reachable after {max_retries} attempts: {e}"
                ) from e
