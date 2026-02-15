# Docker Containerization Expert - Project Memory

## Project: AI Research Platform

### Base Image Standard
- **All containers**: `python:3.11-slim-bookworm` (standardized across project)
- Consistent Debian base ensures compatibility and predictable behavior

### Container Architecture Patterns

#### Standard Python Workers (11 workers)
- chunking, embedding, evaluation, extraction, conflict, auditor, orchestrator, researcher
- Pattern: Simple single-stage builds with minimal dependencies
- Common dependencies: psycopg2-binary, redis, requests
- No system packages needed

#### Crawler Worker (Multi-stage)
- Requires XML parsing libraries: libxml2, libxslt
- Multi-stage build separates build deps (gcc, *-dev) from runtime libs
- Runtime only needs: libxml2, libxslt1.1 (no dev packages)
- Python packages: beautifulsoup4, lxml, PyPDF2, minio

#### Healing Worker (Multi-stage with Docker CLI)
- Needs Docker CLI for container restarts/management
- Multi-stage build to avoid bloat from docker.io package
- Copies only /usr/bin/docker binary from builder
- Optional Claude Code CLI support via build arg
- Note: Non-root user may need docker group membership for socket access

#### Services with HTTP Endpoints
- Backend (FastAPI): Port 8000, uvicorn server
- Monitoring: Port 8001, Flask metrics endpoint
- MCP Server: Port 8002, Starlette server
- All have HEALTHCHECK directives

### Security Hardening Applied
- All containers run as non-root user "appuser"
- User/group created with `groupadd -r appuser && useradd -r -g appuser appuser`
- Files owned by appuser before USER switch
- No shells, package managers, or dev tools in runtime images

### Python Optimizations
Standard ENV variables across all images:
- PYTHONUNBUFFERED=1 (immediate stdout/stderr)
- PYTHONDONTWRITEBYTECODE=1 (no .pyc files)
- PIP_NO_CACHE_DIR=1 (no pip cache)
- PIP_DISABLE_PIP_VERSION_CHECK=1 (faster pip)

### Layer Optimization
- Requirements copied and installed before application code (cache efficiency)
- Python cache removal combined in single RUN layer
- apt-get with --no-install-recommends and same-layer cleanup

### Build Context Optimization
Three .dockerignore files created:
- `/home/casey/project/ai_research/.dockerignore` (root)
- `/home/casey/project/ai_research/backend/.dockerignore`
- `/home/casey/project/ai_research/workers/.dockerignore`

Excludes: Git files, Python cache, venvs, IDE files, tests, docs, env files

### Dependencies Pattern
Most workers share minimal dependencies:
- psycopg2-binary (PostgreSQL)
- redis (Redis client)
- requests (HTTP client)

Specialized dependencies noted in specific Dockerfiles

### File Structure
Backend: /app/app/ (FastAPI application)
Workers: /app/shared/ + /app/worker.py + additional modules
Consistent WORKDIR=/app across all containers
