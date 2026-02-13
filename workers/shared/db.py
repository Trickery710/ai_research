"""PostgreSQL connection pool for workers."""
import psycopg2
import psycopg2.pool
from shared.config import Config

_pool = None


def get_pool():
    """Lazily initialize and return the connection pool."""
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=5,
            dsn=Config.DATABASE_URL
        )
    return _pool


def get_connection():
    """Get a connection from the pool.

    The caller MUST call return_connection() when done.
    """
    return get_pool().getconn()


def return_connection(conn):
    """Return a connection to the pool."""
    get_pool().putconn(conn)


def execute_query(query, params=None, fetch=False):
    """Execute a query with automatic connection management.

    Args:
        query: SQL query string with %s placeholders.
        params: Tuple of parameters.
        fetch: If True, return all rows as a list of tuples.

    Returns:
        List of tuples if fetch=True, else None.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(query, params)
        result = cur.fetchall() if fetch else None
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        return_connection(conn)


def execute_query_one(query, params=None):
    """Execute a query and return a single row as a tuple, or None."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(query, params)
        result = cur.fetchone()
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        return_connection(conn)
