"""Evaluates and validates URLs before submitting for crawling."""
import requests
import os
from researcher.source_registry import is_url_already_crawled, is_domain_blocked, get_domain

# Timeout for HEAD request validation
HEAD_TIMEOUT = int(os.environ.get("URL_CHECK_TIMEOUT", 10))


def validate_url(url):
    """Perform pre-crawl validation on a URL.

    Checks:
    1. URL not already in crawl queue
    2. Domain not blocked
    3. URL is reachable (HEAD request)

    Returns:
        (is_valid, reason) tuple.
    """
    # Check duplicate
    if is_url_already_crawled(url):
        return False, "already_crawled"

    # Check domain block
    domain = get_domain(url)
    if not domain:
        return False, "invalid_url"

    if is_domain_blocked(domain):
        return False, "domain_blocked"

    # HEAD request to check reachability
    try:
        resp = requests.head(url, timeout=HEAD_TIMEOUT, allow_redirects=True)
        if resp.status_code >= 400:
            return False, f"http_{resp.status_code}"
        content_type = resp.headers.get("Content-Type", "")
        if not any(t in content_type for t in ["text/html", "application/pdf", "text/"]):
            return False, f"unsupported_content_type:{content_type[:50]}"
    except requests.exceptions.Timeout:
        return False, "timeout"
    except requests.exceptions.ConnectionError:
        return False, "connection_error"
    except requests.exceptions.RequestException as e:
        return False, f"request_error:{str(e)[:50]}"

    return True, "valid"


def batch_validate(urls):
    """Validate a batch of URLs.

    Args:
        urls: List of URL strings.

    Returns:
        List of (url, is_valid, reason) tuples.
    """
    results = []
    for url in urls:
        is_valid, reason = validate_url(url)
        results.append((url, is_valid, reason))
    return results


def filter_valid_urls(urls):
    """Filter a list of URLs to only valid ones.

    Args:
        urls: List of URL strings.

    Returns:
        List of valid URL strings.
    """
    valid = []
    for url in urls:
        is_valid, reason = validate_url(url)
        if is_valid:
            valid.append(url)
        else:
            print(f"[url_evaluator] Rejected {url}: {reason}")
    return valid
