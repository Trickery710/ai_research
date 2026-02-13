"""PostgreSQL connection pool for the backend API.

Uses RealDictCursor so all queries return dicts instead of tuples,
which makes it easier to construct Pydantic response models.
"""
import psycopg2
import psycopg2.pool
from psycopg2.extras import RealDictCursor
from app.config import Config

_pool = None


def get_pool():
    """Lazily initialize and return the connection pool."""
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=2,
            maxconn=10,
            dsn=Config.DATABASE_URL
        )
    return _pool


def get_connection():
    """Get a connection from the pool. Caller MUST call return_connection()."""
    return get_pool().getconn()


def return_connection(conn):
    """Return a connection to the pool."""
    get_pool().putconn(conn)


def execute_query(query, params=None, fetch=False):
    """Execute a query, returning list of dicts if fetch=True."""
    conn = get_connection()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
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
    """Execute a query and return a single dict, or None."""
    conn = get_connection()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(query, params)
        result = cur.fetchone()
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        return_connection(conn)
