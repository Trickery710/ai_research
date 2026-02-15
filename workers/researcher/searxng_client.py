"""Tier 0: Real web search via SearXNG for discovering DTC code URLs."""
import os
import time
import requests

SEARXNG_BASE_URL = os.environ.get("SEARXNG_URL", "http://searxng:8080")
SEARXNG_TIMEOUT = int(os.environ.get("SEARXNG_TIMEOUT", 15))
MAX_RESULTS_PER_QUERY = int(os.environ.get("SEARXNG_MAX_RESULTS", 10))


def search_dtc(dtc_code, focus=None):
    """Search SearXNG for a DTC code, optionally focused on a topic.

    Args:
        dtc_code: DTC code string (e.g., "P0301").
        focus: Optional focus area like "causes", "diagnostic steps",
               "sensor readings", "TSB".

    Returns:
        List of URL strings from search results.
    """
    query = f"{dtc_code} automotive diagnostic trouble code"
    if focus:
        query += f" {focus}"

    try:
        resp = requests.get(
            f"{SEARXNG_BASE_URL}/search",
            params={
                "q": query,
                "format": "json",
                "categories": "general",
                "language": "en",
            },
            timeout=SEARXNG_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        urls = []
        for result in data.get("results", [])[:MAX_RESULTS_PER_QUERY]:
            url = result.get("url", "")
            if url and url.startswith("http"):
                urls.append(url)
        return urls

    except Exception as e:
        print(f"[searxng] Search failed for '{query}': {e}")
        return []


def search_dtc_batch(dtc_codes, focus=None, delay=2.0):
    """Search for multiple DTC codes with inter-query delay.

    Args:
        dtc_codes: List of DTC code strings.
        focus: Optional focus area.
        delay: Seconds between queries.

    Returns:
        List of (dtc_code, [urls]) tuples.
    """
    results = []
    for code in dtc_codes:
        urls = search_dtc(code, focus=focus)
        results.append((code, urls))
        if len(dtc_codes) > 1:
            time.sleep(delay)
    return results
