# AI Research Refinery v2

A document processing pipeline that crawls, chunks, embeds, evaluates, and extracts structured knowledge from research documents using local LLMs via Ollama.

## Architecture

```
URL / Text
    |
    v
[Crawl] --> [Chunk] --> [Embed] --> [Evaluate] --> [Extract] --> [Conflict Resolution]
                          |              |              |
                      nomic-embed    llama3          llama3
                       (embed)      (reason)        (reason)
```

**Infrastructure:** PostgreSQL (pgvector), Redis (job queues), MinIO (document storage), Ollama (LLM inference)

## Setup

### 1. Configure GPUs

Edit `.env` to match your GPU setup:

```bash
# Single GPU (share everything)
GPU_EMBED=all
GPU_REASON=all

# Dual GPU (isolated)
GPU_EMBED=0
GPU_REASON=1
```

### 2. Start the stack

```bash
docker-compose up -d --build
```

### 3. Pull the models

Models must be pulled into the Ollama containers before workers will function:

```bash
# Embedding model
docker exec refinery_llm_embed ollama pull nomic-embed-text

# Reasoning model
docker exec refinery_llm_reason ollama pull llama3
```

### 4. Verify health

```bash
# Check all containers are running and healthy
docker ps --format "table {{.Names}}\t{{.Status}}"

# Check pipeline stats
curl http://<server-ip>:8000/stats
```

## Usage

Replace `<server-ip>` with your server's IP address (or `localhost` if running locally).

### Crawl a URL

Fetches a web page and feeds it through the full pipeline.

```bash
curl -X POST http://<server-ip>:8000/crawl \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/article", "max_depth": 1}'
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `url` | string | required | URL to crawl |
| `max_depth` | int (0-3) | 1 | How many links deep to follow |

### Ingest text directly

Submit raw text content without crawling.

```bash
curl -X POST http://<server-ip>:8000/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "title": "My Document",
    "content": "The full text content of the document...",
    "source_url": "https://optional-source.com"
  }'
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `title` | string | required | Document title |
| `content` | string | required | Full text content |
| `source_url` | string | null | Optional source URL |

### Search the knowledge base

Semantic search across all processed chunks.

```bash
curl -X POST http://<server-ip>:8000/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "P0300 random misfire causes",
    "limit": 10,
    "min_trust": 0.0,
    "min_relevance": 0.0
  }'
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `query` | string | required | Search query |
| `limit` | int (1-100) | 10 | Max results |
| `min_trust` | float (0-1) | 0.0 | Minimum trust score filter |
| `min_relevance` | float (0-1) | 0.0 | Minimum relevance score filter |

### List documents

```bash
# All documents
curl http://<server-ip>:8000/documents

# Single document details
curl http://<server-ip>:8000/documents/<doc-id>

# Chunks for a document
curl http://<server-ip>:8000/documents/<doc-id>/chunks
```

### DTC (Diagnostic Trouble Codes)

```bash
# List extracted DTCs
curl http://<server-ip>:8000/dtc

# DTC details (causes, diagnostic steps, sensors, TSBs)
curl http://<server-ip>:8000/dtc/<dtc-id>
```

### Check crawl jobs

```bash
# All crawl jobs
curl http://<server-ip>:8000/crawl

# Filter by status
curl "http://<server-ip>:8000/crawl?status=pending"
```

### Pipeline stats

```bash
curl http://<server-ip>:8000/stats
```

Returns document counts, processing stages, queue depths, and chunk statistics.

## Processing Pipeline

Each document flows through these stages in order:

| Stage | Worker | Queue | Description |
|-------|--------|-------|-------------|
| Chunk | `worker-chunking` | `jobs:chunk` | Splits documents into chunks |
| Embed | `worker-embedding` | `jobs:embed` | Generates vector embeddings (nomic-embed-text) |
| Evaluate | `worker-evaluation` | `jobs:evaluate` | Scores trust and relevance (llama3) |
| Extract | `worker-extraction` | `jobs:extract` | Extracts DTCs, causes, diagnostic steps (llama3) |
| Resolve | `worker-conflict` | `jobs:resolve` | Resolves contradictions between sources |

## Troubleshooting

### Containers unhealthy

Check if models are pulled:

```bash
docker exec refinery_llm_embed ollama list
docker exec refinery_llm_reason ollama list
```

If empty, pull them (see Setup step 3).

### Check worker logs

```bash
# All logs
docker-compose logs

# Specific worker
docker-compose logs worker-embedding
docker-compose logs worker-evaluation
```

### Documents stuck in a stage

```bash
# Check queue depths
curl http://<server-ip>:8000/stats

# Check for errors on a document
curl http://<server-ip>:8000/documents/<doc-id>
```

## Ports

| Service | Port |
|---------|------|
| Backend API | 8000 |
| PostgreSQL | 5432 |
| Redis | 6379 |
| MinIO API | 9000 |
| MinIO Console | 9001 |
| Ollama (embed) | 11434 |
| Ollama (reason) | 11435 |
