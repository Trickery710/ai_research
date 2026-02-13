"""Crawler submission API endpoints.

POST /crawl  -- Submit a URL for crawling
GET  /crawl  -- List crawl queue entries
"""
from fastapi import APIRouter, HTTPException
import uuid

import redis

from app.config import Config
from app.db import get_connection, return_connection, execute_query
from app.models import CrawlRequest, CrawlResponse

router = APIRouter()

_redis_client = None


def _get_redis():
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis(
            host=Config.REDIS_HOST,
            port=Config.REDIS_PORT,
            decode_responses=True
        )
    return _redis_client


@router.post("/crawl", response_model=CrawlResponse)
def submit_crawl(req: CrawlRequest):
    """Submit a URL for crawling.

    Creates a row in research.crawl_queue and pushes the row's UUID
    to the jobs:crawl Redis queue. If the URL already exists in the
    queue, its status is reset to 'pending'.
    """
    crawl_id = str(uuid.uuid4())

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO research.crawl_queue (id, url, max_depth, status)
               VALUES (%s, %s, %s, 'pending')
               ON CONFLICT (url) DO UPDATE
               SET status = 'pending', error_message = NULL
               RETURNING id""",
            (crawl_id, req.url, req.max_depth)
        )
        row = cur.fetchone()
        actual_id = str(row[0])
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise HTTPException(
            status_code=500, detail=f"Failed to create crawl job: {e}"
        )
    finally:
        return_connection(conn)

    _get_redis().lpush("jobs:crawl", actual_id)
    return CrawlResponse(status="queued", crawl_id=actual_id, url=req.url)


@router.get("/crawl")
def list_crawl_jobs(status: str = None, limit: int = 50):
    """List crawl queue entries, optionally filtered by status."""
    if status:
        rows = execute_query(
            """SELECT id, url, status, error_message, created_at, completed_at
               FROM research.crawl_queue
               WHERE status = %s
               ORDER BY created_at DESC LIMIT %s""",
            (status, limit), fetch=True
        )
    else:
        rows = execute_query(
            """SELECT id, url, status, error_message, created_at, completed_at
               FROM research.crawl_queue
               ORDER BY created_at DESC LIMIT %s""",
            (limit,), fetch=True
        )
    return rows or []
