"""Generates URLs for DTC code research from templates, SearXNG, and LLM suggestions.

URL generation tiers (in priority order):
    Tier 0: SearXNG real web search (highest quality, real URLs)
    Tier 1: Deterministic URL templates (fast, reliable domains)
    Tier 2: LLM-suggested URLs (creative but may hallucinate)
"""
import json
import os
from shared.ollama_client import generate_completion

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://llm-reason:11434")
REASONING_MODEL = os.environ.get("REASONING_MODEL", "mistral")

# Tier 1: Deterministic URL templates (no LLM needed)
URL_TEMPLATES = [
    "https://www.obd-codes.com/{code_lower}",
    "https://www.engine-codes.com/{code_lower}",
    "https://dtcbase.com/{code_upper}",
    "https://www.autozone.com/diy/check-engine-light/{code_lower}",
]


def generate_template_urls(dtc_code):
    """Tier 1: Generate URLs from deterministic templates.

    Args:
        dtc_code: DTC code string (e.g., "P0301").

    Returns:
        List of URL strings.
    """
    code_lower = dtc_code.lower()
    code_upper = dtc_code.upper()

    urls = []
    for template in URL_TEMPLATES:
        url = template.format(code_lower=code_lower, code_upper=code_upper)
        urls.append(url)

    return urls


def generate_llm_urls(dtc_code, missing_attributes=None):
    """Tier 2: Ask LLM to suggest relevant URLs for a DTC code.

    Args:
        dtc_code: DTC code string.
        missing_attributes: List of missing data types (e.g., ["causes", "diagnostic_steps"]).

    Returns:
        List of URL strings suggested by the LLM.
    """
    missing_str = ", ".join(missing_attributes) if missing_attributes else "general information"

    prompt = f"""You are an automotive diagnostics expert. I need to find reliable online
resources about the diagnostic trouble code {dtc_code}.

Specifically, I'm looking for information about: {missing_str}

Suggest 3-5 specific URLs from well-known automotive repair and diagnostics websites
where I can find detailed information about this code.

Only suggest URLs from these trusted domains:
- obd-codes.com, engine-codes.com, dtcbase.com
- repairpal.com, yourmechanic.com, fixdapp.com
- autozone.com, aa1car.com, troublecodes.net

Respond with ONLY a JSON object:
{{
    "urls": [
        "https://example.com/path/to/{dtc_code.lower()}",
        "https://example2.com/dtc/{dtc_code.upper()}"
    ],
    "reasoning": "brief explanation of why these sources"
}}"""

    try:
        response = generate_completion(
            prompt,
            model=REASONING_MODEL,
            base_url=OLLAMA_BASE_URL,
            temperature=0.3,
            format_json=True,
        )

        result = json.loads(response)
        urls = result.get("urls", [])
        # Validate URLs are strings and look reasonable
        return [u for u in urls if isinstance(u, str) and u.startswith("http")]
    except (json.JSONDecodeError, Exception) as e:
        print(f"[query_generator] LLM URL generation failed: {e}")
        return []


def generate_searxng_urls(dtc_code, missing_attributes=None):
    """Tier 0: Get real URLs from SearXNG web search.

    Args:
        dtc_code: DTC code string.
        missing_attributes: Optional list of missing data types to focus search.

    Returns:
        List of URL strings from search results.
    """
    from searxng_client import search_dtc

    urls = search_dtc(dtc_code)

    # If specific attributes are missing, do focused searches too
    if missing_attributes:
        for attr in missing_attributes[:2]:
            focused = search_dtc(dtc_code, focus=attr)
            urls.extend(focused)

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            unique.append(u)
    return unique


def generate_range_urls(prefix, start, end):
    """Generate template URLs for a range of DTC codes.

    Args:
        prefix: Code prefix (e.g., "P0").
        start: Range start (e.g., 100).
        end: Range end (e.g., 199).

    Returns:
        List of (dtc_code, [urls]) tuples.
    """
    results = []
    for num in range(start, end + 1):
        code = f"{prefix}{num:03d}" if num < 100 else f"{prefix}{num}"
        urls = generate_template_urls(code)
        results.append((code, urls))
    return results


def generate_urls_for_codes(codes, use_llm=False, use_searxng=False,
                            missing_map=None):
    """Generate URLs for a list of specific DTC codes.

    URL generation tiers (in priority order):
        Tier 0: SearXNG real web search (use_searxng=True)
        Tier 1: Deterministic URL templates (always)
        Tier 2: LLM-suggested URLs (use_llm=True)

    Args:
        codes: List of DTC code strings.
        use_llm: Whether to also use LLM for URL suggestions.
        use_searxng: Whether to use SearXNG for real web search.
        missing_map: Optional dict mapping code -> list of missing attributes.

    Returns:
        List of (dtc_code, [urls]) tuples.
    """
    results = []
    for code in codes:
        urls = []

        # Tier 0: Real search
        if use_searxng:
            missing = missing_map.get(code) if missing_map else None
            searxng_urls = generate_searxng_urls(code, missing_attributes=missing)
            urls.extend(searxng_urls)

        # Tier 1: Templates
        urls.extend(generate_template_urls(code))

        # Tier 2: LLM suggestions
        if use_llm:
            missing = missing_map.get(code) if missing_map else None
            llm_urls = generate_llm_urls(code, missing_attributes=missing)
            urls.extend(llm_urls)

        results.append((code, urls))
    return results
