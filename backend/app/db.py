"""PostgreSQL connection pool for the backend API.

Uses RealDictCursor so all queries return dicts instead of tuples,
which makes it easier to construct Pydantic response models.
"""
import psycopg2
import psycopg2.pool
from psycopg2.extras import RealDictCursor
from app.config import Config
import logging
import time

logger = logging.getLogger(__name__)

_pool = None


def get_pool():
    """Lazily initialize and return the connection pool."""
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=2,
            maxconn=10,
            dsn=Config.DATABASE_URL,
            # Add connection timeout and keepalive settings
            connect_timeout=10,
            keepalives=1,
            keepalives_idle=30,
            keepalives_interval=10,
            keepalives_count=5
        )
    return _pool


def get_connection(max_retries=3, retry_delay=1):
    """Get a validated connection from the pool with retry logic."""
    for attempt in range(max_retries):
        try:
            conn = get_pool().getconn()
            # Validate the connection is alive
            conn.isolation_level  # This will raise if connection is dead
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            return conn
        except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
            logger.warning(f"Connection validation failed (attempt {attempt + 1}/{max_retries}): {e}")
            try:
                get_pool().putconn(conn, close=True)  # Close bad connection
            except:
                pass

            if attempt < max_retries - 1:
                time.sleep(retry_delay)
            else:
                # Last attempt failed, recreate pool
                logger.error("All connection attempts failed, recreating pool")
                global _pool
                try:
                    _pool.closeall()
                except:
                    pass
                _pool = None
                raise

    raise psycopg2.OperationalError("Failed to get valid connection after retries")


def return_connection(conn):
    """Return a connection to the pool."""
    try:
        get_pool().putconn(conn)
    except Exception as e:
        logger.warning(f"Failed to return connection to pool: {e}")


def execute_query(query, params=None, fetch=False, max_retries=2):
    """Execute a query with automatic retry on connection failure."""
    last_exception = None

    for attempt in range(max_retries):
        conn = None
        try:
            conn = get_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(query, params)
            result = cur.fetchall() if fetch else None
            conn.commit()
            return result
        except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
            last_exception = e
            logger.warning(f"Query execution failed (attempt {attempt + 1}/{max_retries}): {e}")
            if conn:
                try:
                    conn.rollback()
                except:
                    pass
                try:
                    get_pool().putconn(conn, close=True)  # Close bad connection
                    conn = None
                except:
                    pass

            if attempt < max_retries - 1:
                time.sleep(0.5)
                continue
            raise
        except Exception:
            if conn:
                try:
                    conn.rollback()
                except:
                    pass
            raise
        finally:
            if conn:
                return_connection(conn)

    raise last_exception


def execute_query_one(query, params=None, max_retries=2):
    """Execute a query and return a single dict with automatic retry."""
    last_exception = None

    for attempt in range(max_retries):
        conn = None
        try:
            conn = get_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(query, params)
            result = cur.fetchone()
            conn.commit()
            return result
        except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
            last_exception = e
            logger.warning(f"Query execution failed (attempt {attempt + 1}/{max_retries}): {e}")
            if conn:
                try:
                    conn.rollback()
                except:
                    pass
                try:
                    get_pool().putconn(conn, close=True)  # Close bad connection
                    conn = None
                except:
                    pass

            if attempt < max_retries - 1:
                time.sleep(0.5)
                continue
            raise
        except Exception:
            if conn:
                try:
                    conn.rollback()
                except:
                    pass
            raise
        finally:
            if conn:
                return_connection(conn)

    raise last_exception
