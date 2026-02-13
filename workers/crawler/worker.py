"""Crawler Worker.

Fetches documents from URLs (HTML and PDF), extracts text content,
stores raw text in MinIO, creates a document record in PostgreSQL,
and pushes it to the chunking queue to enter the pipeline.

Queue: jobs:crawl
Payload: crawl_queue row UUID string (NOT a URL -- it is the id
         of a row in research.crawl_queue)
Next: jobs:chunk
"""
import sys
import time
import traceback
import hashlib
import uuid as uuid_mod
from io import BytesIO

sys.path.insert(0, "/app")

import requests
from bs4 import BeautifulSoup

from shared.config import Config
from shared.redis_client import pop_job, push_job
from shared.db import get_connection, return_connection, execute_query
from shared.minio_client import store_content, store_bytes
from shared.pipeline import log_processing


def fetch_url(url, timeout=30):
    """HTTP GET a URL.

    Returns:
        tuple: (content_bytes, content_type_header, status_code)
    """
    headers = {
        "User-Agent": "AIResearchRefinery/2.0 (Automotive Knowledge Engine)"
    }
    response = requests.get(url, headers=headers, timeout=timeout,
                            allow_redirects=True)
    response.raise_for_status()
    content_type = response.headers.get("Content-Type", "").lower()
    return response.content, content_type, response.status_code


def extract_text_from_html(html_bytes):
    """Extract readable text and title from HTML.

    Returns:
        tuple: (text_string, title_string)
    """
    soup = BeautifulSoup(html_bytes, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    return text, title


def extract_text_from_pdf(pdf_bytes):
    """Extract text and title from a PDF.

    Returns:
        tuple: (text_string, title_string)
    """
    from PyPDF2 import PdfReader
    reader = PdfReader(BytesIO(pdf_bytes))
    pages = []
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            pages.append(page_text)
    text = "\n\n".join(pages)
    title = ""
    if reader.metadata and reader.metadata.title:
        title = reader.metadata.title
    return text, title


def process_crawl_job(crawl_id):
    """Fetch a URL, extract text, store in MinIO, create document record."""
    start_time = time.time()

    # Read the crawl queue entry
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT url, depth, max_depth FROM research.crawl_queue WHERE id = %s",
            (crawl_id,)
        )
        row = cur.fetchone()
        if not row:
            print(f"[crawler] Crawl job {crawl_id} not found in crawl_queue")
            return
        url, depth, max_depth = row

        cur.execute(
            "UPDATE research.crawl_queue SET status = 'crawling' WHERE id = %s",
            (crawl_id,)
        )
        conn.commit()
    finally:
        return_connection(conn)

    try:
        content_bytes, content_type, status_code = fetch_url(url)

        if "pdf" in content_type:
            text, title = extract_text_from_pdf(content_bytes)
            mime_type = "application/pdf"
        else:
            text, title = extract_text_from_html(content_bytes)
            mime_type = "text/html"

        if not text or len(text.strip()) < 50:
            raise ValueError(
                f"Extracted text too short ({len(text.strip())} chars)"
            )

        if not title:
            title = url.split("/")[-1][:100] or "Untitled"

        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()

        # Check for duplicate content already in the system
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT id FROM research.documents WHERE content_hash = %s",
                (content_hash,)
            )
            existing = cur.fetchone()
        finally:
            return_connection(conn)

        if existing:
            print(f"[crawler] Duplicate content for {url}, skipping")
            execute_query(
                """UPDATE research.crawl_queue
                   SET status = 'completed', completed_at = NOW()
                   WHERE id = %s""",
                (crawl_id,)
            )
            return

        # Store text in MinIO
        doc_id = str(uuid_mod.uuid4())
        minio_key = f"raw/{doc_id}"
        store_content(minio_key, text, content_type=mime_type)

        # Also store original PDF bytes if applicable
        if mime_type == "application/pdf":
            store_bytes(f"original/{doc_id}.pdf", content_bytes,
                        content_type="application/pdf")

        # Create document record
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO research.documents
                   (id, title, source_url, content_hash, mime_type,
                    minio_bucket, minio_key, processing_stage)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending')""",
                (doc_id, title, url, content_hash, mime_type,
                 Config.MINIO_BUCKET, minio_key)
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            return_connection(conn)

        # Mark crawl as completed
        execute_query(
            """UPDATE research.crawl_queue
               SET status = 'completed', completed_at = NOW()
               WHERE id = %s""",
            (crawl_id,)
        )

        # Push new document into the processing pipeline
        push_job(Config.NEXT_QUEUE, doc_id)

        duration_ms = int((time.time() - start_time) * 1000)
        log_processing(doc_id, "crawling", "completed",
                       f"Fetched {url} ({len(text)} chars)", duration_ms)
        print(f"[crawler] {url} -> doc={doc_id} chars={len(text)} "
              f"ms={duration_ms}")

    except Exception as e:
        execute_query(
            """UPDATE research.crawl_queue
               SET status = 'failed', error_message = %s
               WHERE id = %s""",
            (str(e)[:500], crawl_id)
        )
        raise


def main():
    print(f"[crawler] Worker started. Queue={Config.WORKER_QUEUE} "
          f"Next={Config.NEXT_QUEUE}")

    while True:
        try:
            job = pop_job(Config.WORKER_QUEUE, timeout=Config.POLL_TIMEOUT)
            if job:
                process_crawl_job(job.strip())
        except Exception as e:
            print(f"[crawler] ERROR: {e}")
            traceback.print_exc()
        time.sleep(0.5)


if __name__ == "__main__":
    main()
