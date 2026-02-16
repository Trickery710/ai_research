"""Evaluation Worker.

For each document, evaluates every chunk using the reasoning LLM
(llm-reason on GPU 1). Assigns trust_score (0-1), relevance_score (0-1),
and automotive_domain classification. Stores results in
research.chunk_evaluations.

Queue: jobs:evaluate
Payload: document UUID string
Next: jobs:extract
"""
import sys
import json
import time
import traceback

sys.path.insert(0, "/app")

from shared.config import Config
from shared.redis_client import pop_job
from shared.db import get_connection, return_connection
from shared.ollama_client import generate_completion, ensure_model_available
from shared.pipeline import (
    update_document_stage, log_processing, advance_to_next_stage
)

SYSTEM_PROMPT = """You are an automotive technical content evaluator.
You will be given a text chunk from a technical document, optionally with
web search context for cross-referencing.

Evaluate it and respond with ONLY a JSON object (no other text):

{
  "trust_score": <float 0.0-1.0>,
  "relevance_score": <float 0.0-1.0>,
  "automotive_domain": "<one of: obd, electrical, engine, transmission, brakes, suspension, hvac, body, general, unknown>",
  "reasoning": "<brief explanation>"
}

Scoring guidelines (use the full 0.0-1.0 range, not just fixed tiers):
- trust_score: Rate source credibility on a continuous scale.
  Anchors: ~0.9-1.0 = OEM/factory data, ~0.7-0.85 = professional repair guide or
  well-sourced technical article, ~0.4-0.65 = forum post with specific details or
  community-verified info, ~0.2-0.35 = anecdotal or vague claims,
  ~0.0-0.15 = spam/ads/completely unverifiable.
  Consider: specificity of claims, presence of part numbers or specs,
  technical depth, consistency with known automotive principles.

- relevance_score: Rate diagnostic utility on a continuous scale.
  Anchors: ~0.9-1.0 = step-by-step diagnostic procedure with measurements,
  ~0.7-0.85 = DTC explanation with causes/symptoms, ~0.5-0.65 = general
  automotive knowledge applicable to diagnostics, ~0.25-0.4 = tangentially
  related automotive content, ~0.0-0.2 = not automotive or not useful.
  Consider: actionability, presence of DTC codes, diagnostic value,
  completeness of information.

If web search context is provided, use it to validate claims and adjust
scores accordingly. Corroborated information should score higher."""

VALID_DOMAINS = frozenset([
    "obd", "electrical", "engine", "transmission", "brakes",
    "suspension", "hvac", "body", "general", "unknown"
])


def parse_evaluation(response_text):
    """Parse LLM JSON response with multiple fallback strategies."""
    text = response_text.strip()

    # Strategy 1: direct JSON parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Strategy 2: extract from ```json code block
    if "```json" in text:
        try:
            start = text.index("```json") + 7
            end = text.index("```", start)
            return json.loads(text[start:end].strip())
        except (json.JSONDecodeError, ValueError):
            pass

    # Strategy 3: find outermost braces
    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last > first:
        try:
            return json.loads(text[first:last + 1])
        except json.JSONDecodeError:
            pass

    # Fallback: default scores
    return {
        "trust_score": 0.5,
        "relevance_score": 0.5,
        "automotive_domain": "unknown",
        "reasoning": f"Could not parse LLM response: {text[:200]}"
    }


def clamp(value, lo=0.0, hi=1.0):
    """Clamp a value to [lo, hi], defaulting to 0.5 on failure."""
    try:
        return max(lo, min(hi, float(value)))
    except (TypeError, ValueError):
        return 0.5


def process_document(doc_id):
    """Evaluate all chunks of a document."""
    start_time = time.time()

    update_document_stage(doc_id, "evaluating")
    log_processing(doc_id, "evaluating", "started")

    # Fetch chunks
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT id, content FROM research.document_chunks
               WHERE document_id = %s ORDER BY chunk_index""",
            (doc_id,)
        )
        chunks = cur.fetchall()
    finally:
        return_connection(conn)

    if not chunks:
        raise ValueError(f"No chunks found for document {doc_id}")

    # Import SearxNG search integration
    try:
        from searxng_verify import get_search_context_for_chunk
        search_available = True
    except ImportError:
        search_available = False

    evaluated_count = 0
    for chunk_id, content in chunks:
        # Build search context if available
        search_context = ""
        if search_available:
            try:
                search_context = get_search_context_for_chunk(content)
            except Exception:
                pass  # search is best-effort

        prompt = (
            f"Evaluate this automotive technical content chunk:\n\n"
            f"---\n{content}\n---"
            f"{search_context}"
        )
        response_text = generate_completion(
            prompt=prompt,
            system_prompt=SYSTEM_PROMPT,
            format_json=True,
            temperature=0.1
        )

        result = parse_evaluation(response_text)

        trust = clamp(result.get("trust_score", 0.5))
        relevance = clamp(result.get("relevance_score", 0.5))
        domain = result.get("automotive_domain", "unknown")
        if domain not in VALID_DOMAINS:
            domain = "unknown"
        reasoning = str(result.get("reasoning", ""))[:1000]

        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO research.chunk_evaluations
                   (chunk_id, trust_score, relevance_score, automotive_domain,
                    reasoning, model_used)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT (chunk_id) DO UPDATE
                   SET trust_score = EXCLUDED.trust_score,
                       relevance_score = EXCLUDED.relevance_score,
                       automotive_domain = EXCLUDED.automotive_domain,
                       reasoning = EXCLUDED.reasoning,
                       model_used = EXCLUDED.model_used,
                       evaluated_at = NOW()""",
                (chunk_id, trust, relevance, domain, reasoning,
                 Config.REASONING_MODEL)
            )
            conn.commit()
            evaluated_count += 1
        except Exception:
            conn.rollback()
            raise
        finally:
            return_connection(conn)

    duration_ms = int((time.time() - start_time) * 1000)
    log_processing(doc_id, "evaluating", "completed",
                   f"Evaluated {evaluated_count} chunks", duration_ms)
    advance_to_next_stage(doc_id, "evaluated", "extracting")
    print(f"[evaluation] doc={doc_id} evaluated={evaluated_count} ms={duration_ms}")


def main():
    from shared.graceful import GracefulShutdown, wait_for_db, wait_for_redis

    shutdown = GracefulShutdown()

    print(f"[evaluation] Worker started. Queue={Config.WORKER_QUEUE} "
          f"Ollama={Config.OLLAMA_BASE_URL} Model={Config.REASONING_MODEL}")

    wait_for_db()
    wait_for_redis()

    ensure_model_available(Config.REASONING_MODEL)

    while shutdown.is_running():
        try:
            job = pop_job(Config.WORKER_QUEUE, timeout=Config.POLL_TIMEOUT)
            if job:
                process_document(job.strip())
        except Exception as e:
            print(f"[evaluation] ERROR: {e}")
            traceback.print_exc()
            try:
                if job:
                    update_document_stage(job.strip(), "error", str(e)[:500])
                    log_processing(job.strip(), "evaluating", "failed",
                                   str(e)[:500])
            except Exception:
                pass
        time.sleep(0.1)

    shutdown.cleanup()


if __name__ == "__main__":
    main()
