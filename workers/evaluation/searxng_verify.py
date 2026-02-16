"""SearxNG search integration for evaluation agent.

Provides contextual search capability to help the evaluation agent
make better decisions about trust and relevance scoring by cross-
referencing chunk content against web search results.
"""
import os
import re
import logging
import requests
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)

SEARXNG_URL = os.environ.get("SEARXNG_URL", "http://searxng:8080")
SEARXNG_TIMEOUT = int(os.environ.get("SEARXNG_TIMEOUT", 10))
SEARCH_ENABLED = os.environ.get("EVAL_SEARCH_ENABLED", "true").lower() == "true"


def extract_search_terms(content: str) -> Optional[str]:
    """Extract automotive-relevant search terms from chunk content.

    Looks for DTC codes, part numbers, sensor names, and key phrases.
    Returns a search query string or None if nothing relevant found.
    """
    terms = []

    # Extract DTC codes (P0xxx, B0xxx, C0xxx, U0xxx patterns)
    dtc_codes = re.findall(r'\b[PBCU][0-9A-Fa-f]{4}\b', content)
    if dtc_codes:
        terms.extend(dtc_codes[:2])  # max 2 DTC codes

    # Extract sensor names
    sensor_patterns = [
        r'\b(O2|oxygen|MAP|MAF|TPS|IAT|ECT|CKP|CMP)\s*sensor\b',
        r'\b(knock|speed|pressure|temperature|position)\s*sensor\b',
    ]
    for pattern in sensor_patterns:
        matches = re.findall(pattern, content, re.IGNORECASE)
        if matches:
            terms.append(f"{matches[0]} sensor")
            break

    # Extract key automotive phrases
    if not terms:
        auto_terms = re.findall(
            r'\b(misfire|catalytic|evap|egr|injector|ignition|fuel pump|'
            r'camshaft|crankshaft|throttle|transmission|solenoid)\b',
            content, re.IGNORECASE
        )
        if auto_terms:
            terms.extend(auto_terms[:2])

    if not terms:
        return None

    return " ".join(terms) + " automotive diagnostic"


def search_context(query: str, max_results: int = 3) -> List[Dict]:
    """Search SearxNG for contextual information.

    Returns list of dicts with title, url, snippet.
    """
    if not SEARCH_ENABLED:
        return []

    try:
        resp = requests.get(
            f"{SEARXNG_URL}/search",
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

        results = []
        for r in data.get("results", [])[:max_results]:
            results.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("content", "")[:300],
            })
        return results

    except Exception as e:
        logger.debug(f"SearxNG search failed for '{query}': {e}")
        return []


def build_search_context_prompt(results: List[Dict]) -> str:
    """Build additional context from search results for the LLM prompt."""
    if not results:
        return ""

    context_parts = ["\n\nWeb search context for cross-reference:"]
    for i, r in enumerate(results, 1):
        snippet = r.get("snippet", "").strip()
        if snippet:
            context_parts.append(f"[{i}] {r.get('title', 'Source')}: {snippet}")

    return "\n".join(context_parts)


def get_search_context_for_chunk(content: str) -> str:
    """Get search context for a chunk if relevant terms are found.

    Returns additional prompt text or empty string.
    """
    if not SEARCH_ENABLED:
        return ""

    query = extract_search_terms(content)
    if not query:
        return ""

    results = search_context(query)
    return build_search_context_prompt(results)
