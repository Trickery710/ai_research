"""OpenAI API client with multi-key rotation and rate limit tracking.

Supports multiple API keys loaded from environment. Tracks per-key rate limits
in Redis and enforces 90% budget utilization before reset windows.

Key sources (checked in order):
    OPENAI_API_KEYS=sk-key1,sk-key2,sk-key3
    OPENAI_API_KEY_1=sk-key1  OPENAI_API_KEY_2=sk-key2
    OPENAI_API_KEY=sk-key1  (single key fallback)
"""
import os
import re
import time
import json
import requests

from shared.redis_client import get_redis

OPENAI_API_BASE = "https://api.openai.com/v1"
KEY_PREFIX = "verify:openai:key:"


class OpenAIKeyManager:
    """Manages multiple OpenAI API keys with Redis-backed rate limit tracking.

    Per-key Redis hash at verify:openai:key:{key_id}:info stores:
        requests_made, tokens_used, rate_limit_remaining,
        rate_limit_reset (unix ts), budget_limit_requests (90% of limit),
        budget_limit_tokens (90% of token limit), last_used, last_error
    """

    def __init__(self):
        self.keys = self._load_keys()
        self.r = get_redis()
        self._init_redis_state()

    def _load_keys(self):
        """Load API keys from environment variables."""
        keys = {}

        # Try comma-separated list first
        csv_keys = os.environ.get("OPENAI_API_KEYS", "")
        if csv_keys:
            for i, key in enumerate(csv_keys.split(","), 1):
                key = key.strip()
                if key:
                    keys[f"key_{i}"] = key

        # Also check numbered env vars
        for i in range(1, 20):
            env_key = os.environ.get(f"OPENAI_API_KEY_{i}", "")
            if env_key:
                key_id = f"key_{i}"
                if key_id not in keys:
                    keys[key_id] = env_key

        # Fall back to single key
        if not keys:
            single = os.environ.get("OPENAI_API_KEY", "")
            if single:
                keys["key_1"] = single

        if not keys:
            print("[openai_client] WARNING: No OpenAI API keys configured")

        return keys

    def _init_redis_state(self):
        """Initialize Redis tracking state for each key."""
        for key_id in self.keys:
            info_key = f"{KEY_PREFIX}{key_id}:info"
            if not self.r.exists(info_key):
                self.r.hset(info_key, mapping={
                    "requests_made": 0,
                    "tokens_used": 0,
                    "rate_limit_remaining": 10000,
                    "rate_limit_reset": 0,
                    "last_used": 0,
                    "last_error": "",
                    "budget_limit_requests": 9000,
                    "budget_limit_tokens": 900000,
                })

    def get_best_key(self):
        """Select the best key based on remaining quota.

        Returns:
            (key_id, api_key) tuple, or (None, None) if all exhausted.
        """
        now = time.time()
        best_key_id = None
        best_score = -1

        for key_id in self.keys:
            info_key = f"{KEY_PREFIX}{key_id}:info"
            info = self.r.hgetall(info_key)

            remaining = int(info.get("rate_limit_remaining", 10000))
            reset_time = float(info.get("rate_limit_reset", 0))
            requests_made = int(info.get("requests_made", 0))
            budget_limit = int(info.get("budget_limit_requests", 9000))

            # If rate limit has reset, reset counters
            if reset_time > 0 and now > reset_time:
                self.r.hset(info_key, mapping={
                    "requests_made": 0,
                    "tokens_used": 0,
                    "rate_limit_remaining": 10000,
                    "rate_limit_reset": 0,
                })
                remaining = 10000
                requests_made = 0

            # Skip if we've used 90% of budget
            if requests_made >= budget_limit:
                continue

            score = remaining - requests_made
            if score > best_score:
                best_score = score
                best_key_id = key_id

        if best_key_id:
            return best_key_id, self.keys[best_key_id]
        return None, None

    def record_usage(self, key_id, tokens_used, response_headers):
        """Update Redis tracking after an API call.

        Parses OpenAI x-ratelimit-* headers for remaining quota and reset time.
        """
        info_key = f"{KEY_PREFIX}{key_id}:info"

        pipe = self.r.pipeline()
        pipe.hincrby(info_key, "requests_made", 1)
        pipe.hincrby(info_key, "tokens_used", tokens_used)
        pipe.hset(info_key, "last_used", str(time.time()))

        remaining = response_headers.get("x-ratelimit-remaining-requests")
        reset = response_headers.get("x-ratelimit-reset-requests")
        token_remaining = response_headers.get("x-ratelimit-remaining-tokens")

        if remaining is not None:
            pipe.hset(info_key, "rate_limit_remaining", str(remaining))
            # Set budget to 90% of the limit we can infer
            requests_made = int(self.r.hget(info_key, "requests_made") or 0)
            total_limit = requests_made + int(remaining)
            pipe.hset(info_key, "budget_limit_requests",
                       str(int(total_limit * 0.9)))

        if reset is not None:
            reset_seconds = self._parse_reset_duration(str(reset))
            pipe.hset(info_key, "rate_limit_reset",
                       str(time.time() + reset_seconds))

        if token_remaining is not None:
            tokens_made = int(self.r.hget(info_key, "tokens_used") or 0)
            total_tokens = tokens_made + int(token_remaining)
            pipe.hset(info_key, "budget_limit_tokens",
                       str(int(total_tokens * 0.9)))

        pipe.execute()

    def record_error(self, key_id, error_msg):
        """Record an error for a key."""
        info_key = f"{KEY_PREFIX}{key_id}:info"
        self.r.hset(info_key, "last_error", str(error_msg)[:500])

    def _parse_reset_duration(self, duration_str):
        """Parse OpenAI reset duration like '6m0s' or '1h30m0s' to seconds."""
        total = 0
        hours = re.search(r'(\d+)h', duration_str)
        minutes = re.search(r'(\d+)m', duration_str)
        seconds = re.search(r'(\d+(?:\.\d+)?)s', duration_str)
        if hours:
            total += int(hours.group(1)) * 3600
        if minutes:
            total += int(minutes.group(1)) * 60
        if seconds:
            total += float(seconds.group(1))
        return total if total > 0 else 60

    def get_all_key_stats(self):
        """Get usage stats for all keys (for monitoring/logging)."""
        stats = {}
        for key_id in self.keys:
            info_key = f"{KEY_PREFIX}{key_id}:info"
            info = self.r.hgetall(info_key)
            stats[key_id] = {
                "requests_made": int(info.get("requests_made", 0)),
                "tokens_used": int(info.get("tokens_used", 0)),
                "rate_limit_remaining": int(info.get("rate_limit_remaining", 0)),
                "rate_limit_reset": float(info.get("rate_limit_reset", 0)),
                "last_used": float(info.get("last_used", 0)),
                "last_error": info.get("last_error", ""),
            }
        return stats


_key_manager = None


def get_key_manager():
    """Get or create the singleton key manager."""
    global _key_manager
    if _key_manager is None:
        _key_manager = OpenAIKeyManager()
    return _key_manager


def chat_completion(messages, model="gpt-4o-mini", temperature=0.1,
                    max_tokens=1000, _retry_depth=0):
    """Make an OpenAI chat completion with automatic key rotation.

    Args:
        messages: List of message dicts.
        model: Model name.
        temperature: Sampling temperature.
        max_tokens: Max tokens in response.

    Returns:
        (response_text, key_id, tokens_used) tuple.

    Raises:
        RuntimeError: If no API keys are available.
    """
    if _retry_depth > 5:
        raise RuntimeError("All OpenAI API keys exhausted after retries")

    mgr = get_key_manager()
    key_id, api_key = mgr.get_best_key()

    if not api_key:
        raise RuntimeError("No OpenAI API keys available (all rate-limited)")

    try:
        resp = requests.post(
            f"{OPENAI_API_BASE}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=60,
        )
        resp.raise_for_status()

        data = resp.json()
        text = data["choices"][0]["message"]["content"]
        tokens_used = data.get("usage", {}).get("total_tokens", 0)

        mgr.record_usage(key_id, tokens_used, resp.headers)
        return text, key_id, tokens_used

    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 429:
            mgr.record_error(key_id, "rate_limited")
            return chat_completion(messages, model, temperature, max_tokens,
                                   _retry_depth + 1)
        mgr.record_error(key_id, str(e))
        raise
