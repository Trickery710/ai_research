"""API key authentication middleware for the backend."""
import os
from fastapi import Request, HTTPException, Security
from fastapi.security import APIKeyHeader

# Comma-separated list of valid API keys from environment
_raw = os.environ.get("API_KEYS", "")
VALID_API_KEYS = set(k.strip() for k in _raw.split(",") if k.strip())

# Auth is disabled when no API_KEYS are configured (dev mode)
AUTH_ENABLED = len(VALID_API_KEYS) > 0

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# Paths that never require authentication
PUBLIC_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}


async def verify_api_key(request: Request, api_key: str = Security(api_key_header)):
    """Dependency that validates API key if auth is enabled."""
    if not AUTH_ENABLED:
        return None

    # Allow public paths
    if request.url.path in PUBLIC_PATHS:
        return None

    if not api_key or api_key not in VALID_API_KEYS:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key. Provide X-API-Key header.",
        )
    return api_key
