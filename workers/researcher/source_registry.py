"""Tracks domain quality, deduplication, and blocked domains."""
import json
from urllib.parse import urlparse
from shared.db import execute_query, execute_query_one


# Default known automotive sources with quality tiers (1=best, 5=worst)
DEFAULT_SOURCES = [
    {"domain": "obd-codes.com", "quality_tier": 2, "source_type": "template"},
    {"domain": "engine-codes.com", "quality_tier": 2, "source_type": "template"},
    {"domain": "dtcbase.com", "quality_tier": 2, "source_type": "template"},
    {"domain": "www.autozone.com", "quality_tier": 3, "source_type": "template"},
    {"domain": "www.obd-codes.com", "quality_tier": 2, "source_type": "template"},
    {"domain": "repairpal.com", "quality_tier": 3, "source_type": "llm_suggested"},
    {"domain": "www.fixdapp.com", "quality_tier": 3, "source_type": "llm_suggested"},
    {"domain": "www.yourmechanic.com", "quality_tier": 3, "source_type": "llm_suggested"},
]


def init_default_sources():
    """Seed the research_sources table with known domains."""
    for src in DEFAULT_SOURCES:
        execute_query(
            """INSERT INTO research.research_sources
               (domain, source_type, quality_tier)
               VALUES (%s, %s, %s)
               ON CONFLICT (domain) DO NOTHING""",
            (src["domain"], src["source_type"], src["quality_tier"])
        )
    print(f"[source_registry] Initialized {len(DEFAULT_SOURCES)} default sources")


def get_domain(url):
    """Extract domain from URL."""
    try:
        parsed = urlparse(url)
        return parsed.netloc.lower()
    except Exception:
        return None


def is_domain_blocked(domain):
    """Check if a domain is blocked.

    Returns:
        True if domain is blocked.
    """
    row = execute_query_one(
        """SELECT is_blocked FROM research.research_sources
        WHERE domain = %s""",
        (domain,)
    )
    return row[0] if row else False


def get_domain_quality(domain):
    """Get quality tier for a domain.

    Returns:
        int quality tier (1-5) or 3 (default) if unknown.
    """
    row = execute_query_one(
        "SELECT quality_tier FROM research.research_sources WHERE domain = %s",
        (domain,)
    )
    return row[0] if row else 3


def register_domain(domain, source_type="discovered", quality_tier=3):
    """Register a new domain in the source registry."""
    execute_query(
        """INSERT INTO research.research_sources
           (domain, source_type, quality_tier)
           VALUES (%s, %s, %s)
           ON CONFLICT (domain) DO NOTHING""",
        (domain, source_type, quality_tier)
    )


def record_crawl(domain, trust_score=None):
    """Record that we crawled a URL from this domain.

    Updates crawl counts and running average trust score.
    """
    if trust_score is not None:
        execute_query(
            """UPDATE research.research_sources
               SET total_urls_crawled = total_urls_crawled + 1,
                   last_crawled_at = NOW(),
                   avg_trust_score = (avg_trust_score * total_urls_crawled + %s)
                                     / (total_urls_crawled + 1)
               WHERE domain = %s""",
            (trust_score, domain)
        )
    else:
        execute_query(
            """UPDATE research.research_sources
               SET total_urls_crawled = total_urls_crawled + 1,
                   last_crawled_at = NOW()
               WHERE domain = %s""",
            (domain,)
        )


def is_url_already_crawled(url):
    """Check if this URL has already been submitted to the crawl queue.

    Returns:
        True if URL exists in crawl_queue.
    """
    row = execute_query_one(
        "SELECT COUNT(*) FROM research.crawl_queue WHERE url = %s",
        (url,)
    )
    return row[0] > 0 if row else False


def get_active_sources(limit=50):
    """Get all non-blocked sources ordered by quality.

    Returns:
        List of source dicts.
    """
    rows = execute_query(
        """SELECT domain, source_type, quality_tier, total_urls_crawled,
                  avg_trust_score, last_crawled_at
        FROM research.research_sources
        WHERE is_blocked = FALSE
        ORDER BY quality_tier ASC, total_urls_crawled DESC
        LIMIT %s""",
        (limit,),
        fetch=True
    )
    return [
        {
            "domain": r[0],
            "source_type": r[1],
            "quality_tier": r[2],
            "total_crawled": r[3],
            "avg_trust": round(float(r[4]), 4) if r[4] else 0,
            "last_crawled": str(r[5]) if r[5] else None,
        }
        for r in (rows or [])
    ]
