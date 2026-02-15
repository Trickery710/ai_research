"""Researcher worker: discovers and submits new automotive diagnostic URLs.

Operates in two modes:
  1. Directive mode: Listens for orchestrator directives (takes priority)
  2. Autonomous mode: Continuously fills knowledge gaps using SearXNG + templates

When idle (no directives), the autonomous loop identifies gaps in the database
and searches for URLs to fill them.
"""
import sys
import os
import time
import traceback
import json
import uuid
import re

sys.path.insert(0, "/app")

from shared.config import Config
from shared.redis_client import get_redis, pop_job, push_job
from shared.db import execute_query, execute_query_one

RESEARCH_QUEUE = "orchestrator:research"
COMMAND_QUEUE = "orchestrator:commands"
RESULTS_QUEUE = "researcher:results"

# Rate limiting
MAX_URLS_PER_HOUR = int(os.environ.get("MAX_URLS_PER_HOUR", 30))
MAX_PER_DOMAIN_PER_HOUR = int(os.environ.get("MAX_PER_DOMAIN_PER_HOUR", 5))
COOLDOWN_SECONDS = int(os.environ.get("RESEARCH_COOLDOWN", 30))
RATE_LIMIT_KEY = "researcher:rate:total"
DOMAIN_RATE_PREFIX = "researcher:rate:domain:"

_last_submission = 0

# Autonomous research mode
AUTONOMOUS_MODE = os.environ.get("AUTONOMOUS_MODE", "true").lower() == "true"
AUTONOMOUS_INTERVAL = int(os.environ.get("AUTONOMOUS_INTERVAL", 60))
AUTONOMOUS_URLS_PER_CYCLE = int(os.environ.get("AUTONOMOUS_URLS_PER_CYCLE", 4))

_last_autonomous_cycle = 0


def check_rate_limit(domain=None):
    """Check if we're within rate limits.

    Returns:
        (allowed, reason) tuple.
    """
    r = get_redis()

    # Global rate limit
    total = r.get(RATE_LIMIT_KEY)
    if total and int(total) >= MAX_URLS_PER_HOUR:
        return False, f"global_limit ({MAX_URLS_PER_HOUR}/hr)"

    # Per-domain rate limit
    if domain:
        domain_key = f"{DOMAIN_RATE_PREFIX}{domain}"
        domain_count = r.get(domain_key)
        if domain_count and int(domain_count) >= MAX_PER_DOMAIN_PER_HOUR:
            return False, f"domain_limit ({MAX_PER_DOMAIN_PER_HOUR}/hr)"

    # Cooldown
    global _last_submission
    if time.time() - _last_submission < COOLDOWN_SECONDS:
        return False, f"cooldown ({COOLDOWN_SECONDS}s)"

    return True, "ok"


def increment_rate_counters(domain):
    """Increment rate limit counters with TTL."""
    r = get_redis()

    # Global counter with 1-hour TTL
    pipe = r.pipeline()
    pipe.incr(RATE_LIMIT_KEY)
    pipe.expire(RATE_LIMIT_KEY, 3600)

    # Domain counter with 1-hour TTL
    domain_key = f"{DOMAIN_RATE_PREFIX}{domain}"
    pipe.incr(domain_key)
    pipe.expire(domain_key, 3600)

    pipe.execute()

    global _last_submission
    _last_submission = time.time()


def submit_url(url):
    """Submit a URL to the crawl pipeline.

    Creates a crawl_queue entry and pushes to jobs:crawl.

    Returns:
        crawl_id string or None on failure.
    """
    from source_registry import get_domain, register_domain

    domain = get_domain(url)
    if not domain:
        return None

    # Check rate limits
    allowed, reason = check_rate_limit(domain)
    if not allowed:
        print(f"[researcher] Rate limited: {reason} for {url}")
        return None

    crawl_id = str(uuid.uuid4())

    try:
        row = execute_query_one(
            """INSERT INTO research.crawl_queue (id, url, max_depth, status)
               VALUES (%s, %s, 1, 'pending')
               ON CONFLICT (url) DO NOTHING
               RETURNING id""",
            (crawl_id, url)
        )

        if not row:
            # URL already exists
            return None

        actual_id = str(row[0])

        # Push to crawl queue
        push_job("jobs:crawl", actual_id)

        # Register domain if new
        register_domain(domain)
        increment_rate_counters(domain)

        print(f"[researcher] Submitted: {url} (crawl_id={actual_id})")
        return actual_id

    except Exception as e:
        print(f"[researcher] Failed to submit {url}: {e}")
        return None


def handle_research_directive(directive_json):
    """Process a research directive from the orchestrator.

    Directive types:
      - improve_confidence: Research specific codes with low confidence
      - fill_gaps: Fill missing data for specific codes
      - expand_coverage: Explore code ranges for new codes
      - manual: User-initiated research for specific codes
    """
    from query_generator import (
        generate_template_urls,
        generate_urls_for_codes,
        generate_range_urls,
    )
    from url_evaluator import validate_url
    from source_registry import is_url_already_crawled

    try:
        directive = json.loads(directive_json)
    except json.JSONDecodeError:
        print(f"[researcher] Invalid directive JSON: {directive_json[:100]}")
        return

    dtype = directive.get("type", "general")
    task_id = directive.get("task_id")
    target_codes = directive.get("target_codes", [])
    target_ranges = directive.get("target_ranges", [])

    print(f"[researcher] Directive: {dtype}, codes={target_codes[:5]}, ranges={target_ranges[:3]}")

    submitted = 0
    failed = 0

    # Process target codes
    if target_codes:
        use_llm = dtype in ("improve_confidence", "fill_gaps")
        code_urls = generate_urls_for_codes(
            target_codes, use_llm=use_llm, use_searxng=True)

        for code, urls in code_urls:
            for url in urls:
                is_valid, reason = validate_url(url)
                if is_valid:
                    result = submit_url(url)
                    if result:
                        submitted += 1
                    else:
                        failed += 1
                else:
                    failed += 1

                # Respect rate limits
                if submitted > 0 and submitted % 5 == 0:
                    time.sleep(COOLDOWN_SECONDS)

    # Process target ranges
    if target_ranges:
        for range_str in target_ranges:
            # Parse range like "P0100-P0199"
            match = re.match(r'^([PBCU]\d)(\d{2,3})-[PBCU]\d(\d{2,3})$', range_str)
            if not match:
                print(f"[researcher] Invalid range: {range_str}")
                continue

            prefix = match.group(1)
            start = int(match.group(2))
            end = int(match.group(3))

            range_results = generate_range_urls(prefix, start, end)
            for code, urls in range_results:
                # Just use first template URL per code for range expansion
                if urls:
                    is_valid, reason = validate_url(urls[0])
                    if is_valid:
                        result = submit_url(urls[0])
                        if result:
                            submitted += 1

                    # Respect rate limits
                    allowed, _ = check_rate_limit()
                    if not allowed:
                        print(f"[researcher] Rate limit reached, pausing range expansion")
                        break

    print(f"[researcher] Directive complete: submitted={submitted}, failed={failed}")

    # Report back to orchestrator
    push_job(COMMAND_QUEUE, json.dumps({
        "source": "researcher",
        "type": "research_complete",
        "task_id": task_id,
        "result": {
            "directive_type": dtype,
            "urls_submitted": submitted,
            "urls_failed": failed,
        },
    }))

    # Update research plan if applicable
    if task_id:
        execute_query(
            """INSERT INTO research.research_plans
               (plan_type, target_dtc_codes, priority, status,
                urls_submitted, urls_successful)
               VALUES (%s, %s, 5, 'completed', %s, %s)""",
            (dtype, target_codes, submitted + failed, submitted)
        )


def run_autonomous_cycle():
    """One cycle of autonomous gap-filling research.

    Asks the reasoning LLM to look at the database state and decide what
    search queries to run. Then executes those queries via SearXNG and
    submits discovered URLs to the crawl pipeline.
    """
    global _last_autonomous_cycle

    from gap_analyzer import get_research_plan
    from url_evaluator import validate_url

    # Ask the LLM what to research
    searches = get_research_plan()
    if not searches:
        _last_autonomous_cycle = time.time()
        print("[researcher] Autonomous cycle: LLM returned no searches")
        return

    submitted = 0
    queries_run = 0

    for search in searches:
        if submitted >= AUTONOMOUS_URLS_PER_CYCLE:
            break

        query = search.get("query", "")
        reason = search.get("reason", "")
        if not query:
            continue

        print(f"[researcher] Searching: {query} ({reason})")

        # Run the LLM-crafted query through SearXNG
        try:
            from searxng_client import SEARXNG_BASE_URL, SEARXNG_TIMEOUT
            import requests as _requests
            resp = _requests.get(
                f"{SEARXNG_BASE_URL}/search",
                params={"q": query, "format": "json", "language": "en"},
                timeout=SEARXNG_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            urls = [r["url"] for r in data.get("results", [])[:10]
                    if r.get("url", "").startswith("http")]
        except Exception as e:
            print(f"[researcher] SearXNG error for '{query}': {e}")
            urls = []

        queries_run += 1

        for url in urls:
            if submitted >= AUTONOMOUS_URLS_PER_CYCLE:
                break
            is_valid, _ = validate_url(url)
            if is_valid:
                result = submit_url(url)
                if result:
                    submitted += 1
                    time.sleep(COOLDOWN_SECONDS)

    _last_autonomous_cycle = time.time()
    print(f"[researcher] Autonomous cycle: {queries_run} queries, "
          f"{submitted} URLs submitted")

    # Report autonomous activity to orchestrator
    push_job(COMMAND_QUEUE, json.dumps({
        "source": "researcher",
        "type": "autonomous_cycle",
        "result": {
            "urls_submitted": submitted,
            "queries_run": queries_run,
            "searches_planned": len(searches),
        },
    }))


def main():
    from source_registry import init_default_sources

    print(f"[researcher] Worker started. Queue={RESEARCH_QUEUE}")
    print(f"[researcher] Autonomous={AUTONOMOUS_MODE}, "
          f"interval={AUTONOMOUS_INTERVAL}s, "
          f"urls/cycle={AUTONOMOUS_URLS_PER_CYCLE}")
    print(f"[researcher] Rate limits: {MAX_URLS_PER_HOUR}/hr total, "
          f"{MAX_PER_DOMAIN_PER_HOUR}/domain/hr, {COOLDOWN_SECONDS}s cooldown")

    init_default_sources()

    while True:
        try:
            # Check for orchestrator directives (short timeout)
            directive = pop_job(RESEARCH_QUEUE, timeout=2)
            if directive:
                handle_research_directive(directive)
                continue  # Directives take priority

            # Autonomous mode: fill gaps when idle
            if AUTONOMOUS_MODE:
                elapsed = time.time() - _last_autonomous_cycle
                if elapsed >= AUTONOMOUS_INTERVAL:
                    allowed, _ = check_rate_limit()
                    if allowed:
                        run_autonomous_cycle()

        except Exception as e:
            print(f"[researcher] ERROR: {e}")
            traceback.print_exc()

        time.sleep(1)


if __name__ == "__main__":
    main()
