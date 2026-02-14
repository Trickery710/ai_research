"""Extraction Worker.

For each document, processes every chunk with relevance_score >= 0.3
through the reasoning LLM (llm-reason on GPU 1) to extract structured
automotive data: DTC codes, causes, diagnostic steps, sensors, and
TSB references. Inserts results into the refined schema tables.

Queue: jobs:extract
Payload: document UUID string
Next: jobs:resolve
"""
import sys
import json
import time
import traceback
import uuid as uuid_mod

sys.path.insert(0, "/app")

from shared.config import Config
from shared.redis_client import pop_job
from shared.db import get_connection, return_connection
from shared.ollama_client import generate_completion, ensure_model_available
from shared.pipeline import (
    update_document_stage, log_processing, advance_to_next_stage
)

SYSTEM_PROMPT = """You are an automotive technical data extractor.
Given a text chunk, extract all structured automotive data.
Respond with ONLY a JSON object (no other text):

{
  "dtc_codes": [
    {
      "code": "P0171",
      "description": "System Too Lean Bank 1",
      "category": "powertrain",
      "severity": "moderate"
    }
  ],
  "causes": [
    {
      "dtc_code": "P0171",
      "description": "Vacuum leak in intake manifold",
      "likelihood": "high"
    }
  ],
  "diagnostic_steps": [
    {
      "dtc_code": "P0171",
      "step_order": 1,
      "description": "Check for vacuum leaks using smoke test",
      "tools_required": "Smoke machine",
      "expected_values": "No smoke visible from intake"
    }
  ],
  "sensors": [
    {
      "name": "MAF Sensor",
      "sensor_type": "mass_air_flow",
      "typical_range": "2-7 g/s at idle",
      "unit": "g/s",
      "related_dtc_codes": ["P0171", "P0101"]
    }
  ],
  "tsb_references": [
    {
      "tsb_number": "TSB-2023-0142",
      "title": "Intake Manifold Gasket Update",
      "affected_models": "2019-2022 Model X",
      "related_dtc_codes": ["P0171"],
      "summary": "Updated gasket material to prevent vacuum leaks"
    }
  ]
}

Rules:
- Only extract data EXPLICITLY stated in the text. Do not fabricate.
- Return empty arrays for categories with no matches.
- category: powertrain, chassis, body, or network
- severity: critical, moderate, minor, or informational
- likelihood: high, medium, or low"""


def parse_extraction(response_text):
    """Parse extraction JSON with fallback strategies."""
    text = response_text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    if "```json" in text:
        try:
            start = text.index("```json") + 7
            end = text.index("```", start)
            return json.loads(text[start:end].strip())
        except (json.JSONDecodeError, ValueError):
            pass

    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last > first:
        try:
            return json.loads(text[first:last + 1])
        except json.JSONDecodeError:
            pass

    return {
        "dtc_codes": [], "causes": [], "diagnostic_steps": [],
        "sensors": [], "tsb_references": []
    }


def _to_str_list(val):
    """Ensure a value is a list of strings for TEXT[] columns."""
    if isinstance(val, list):
        return [str(v) for v in val if not isinstance(v, dict)]
    if isinstance(val, str):
        return [val]
    return []


def _safe_str(val, default=""):
    """Convert a value to string, returning default if it's a dict/list."""
    if isinstance(val, (dict, list)):
        return json.dumps(val)
    return str(val) if val else default


def store_extraction(chunk_id, data):
    """Insert extracted data into the refined schema tables.

    Uses upserts (ON CONFLICT) to handle duplicates gracefully.
    DTC codes are unique on 'code'; when a duplicate is found,
    the source_count is incremented and description/category/severity
    are filled in if previously empty.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()

        # --- DTC CODES ---
        for dtc in data.get("dtc_codes", []):
            code = (dtc.get("code") or "").strip().upper()
            if not code:
                continue

            cur.execute(
                """INSERT INTO refined.dtc_codes
                   (code, description, category, severity,
                    confidence_score, source_count)
                   VALUES (%s, %s, %s, %s, 0.5, 1)
                   ON CONFLICT (code) DO UPDATE
                   SET description = COALESCE(
                       NULLIF(EXCLUDED.description, ''),
                       refined.dtc_codes.description),
                   category = COALESCE(
                       NULLIF(EXCLUDED.category, ''),
                       refined.dtc_codes.category),
                   severity = COALESCE(
                       NULLIF(EXCLUDED.severity, ''),
                       refined.dtc_codes.severity),
                   source_count = refined.dtc_codes.source_count + 1,
                   updated_at = NOW()
                   RETURNING id""",
                (code, _safe_str(dtc.get("description", "")),
                 _safe_str(dtc.get("category", "")),
                 _safe_str(dtc.get("severity", "")))
            )
            dtc_row = cur.fetchone()
            if not dtc_row:
                continue
            dtc_id = dtc_row[0]

            # Link DTC to source chunk
            cur.execute(
                """INSERT INTO refined.dtc_sources (dtc_id, chunk_id)
                   VALUES (%s, %s)
                   ON CONFLICT (dtc_id, chunk_id) DO NOTHING""",
                (dtc_id, chunk_id)
            )

            # --- CAUSES for this DTC ---
            for cause in data.get("causes", []):
                if (cause.get("dtc_code") or "").strip().upper() != code:
                    continue
                desc = (cause.get("description") or "").strip()
                if not desc:
                    continue
                cur.execute(
                    """INSERT INTO refined.causes
                       (dtc_id, description, likelihood,
                        source_chunk_id, confidence_score)
                       VALUES (%s, %s, %s, %s, 0.5)""",
                    (dtc_id, desc,
                     _safe_str(cause.get("likelihood", "medium")),
                     chunk_id)
                )

            # --- DIAGNOSTIC STEPS for this DTC ---
            for step in data.get("diagnostic_steps", []):
                if (step.get("dtc_code") or "").strip().upper() != code:
                    continue
                desc = (step.get("description") or "").strip()
                if not desc:
                    continue
                cur.execute(
                    """INSERT INTO refined.diagnostic_steps
                       (dtc_id, step_order, description, tools_required,
                        expected_values, source_chunk_id, confidence_score)
                       VALUES (%s, %s, %s, %s, %s, %s, 0.5)""",
                    (dtc_id, step.get("step_order", 0), desc,
                     _safe_str(step.get("tools_required", "")),
                     _safe_str(step.get("expected_values", "")),
                     chunk_id)
                )

        # --- SENSORS (not DTC-specific) ---
        for sensor in data.get("sensors", []):
            name = (sensor.get("name") or "").strip()
            if not name:
                continue
            sensor_type = (sensor.get("sensor_type") or "").strip()
            cur.execute(
                """INSERT INTO refined.sensors
                   (name, sensor_type, typical_range, unit,
                    related_dtc_codes, source_chunk_id, confidence_score)
                   VALUES (%s, %s, %s, %s, %s, %s, 0.5)
                   ON CONFLICT (name, sensor_type) DO UPDATE
                   SET typical_range = COALESCE(
                       NULLIF(EXCLUDED.typical_range, ''),
                       refined.sensors.typical_range),
                   unit = COALESCE(
                       NULLIF(EXCLUDED.unit, ''),
                       refined.sensors.unit)""",
                (name, sensor_type,
                 _safe_str(sensor.get("typical_range", "")),
                 _safe_str(sensor.get("unit", "")),
                 _to_str_list(sensor.get("related_dtc_codes", [])),
                 chunk_id)
            )

        # --- TSB REFERENCES ---
        for tsb in data.get("tsb_references", []):
            tsb_num = (tsb.get("tsb_number") or "").strip()
            if not tsb_num:
                continue
            cur.execute(
                """INSERT INTO refined.tsb_references
                   (tsb_number, title, affected_models, related_dtc_codes,
                    summary, source_chunk_id, confidence_score)
                   VALUES (%s, %s, %s, %s, %s, %s, 0.5)
                   ON CONFLICT (tsb_number) DO UPDATE
                   SET title = COALESCE(
                       NULLIF(EXCLUDED.title, ''),
                       refined.tsb_references.title),
                   summary = COALESCE(
                       NULLIF(EXCLUDED.summary, ''),
                       refined.tsb_references.summary)""",
                (tsb_num, _safe_str(tsb.get("title", "")),
                 _safe_str(tsb.get("affected_models", "")),
                 _to_str_list(tsb.get("related_dtc_codes", [])),
                 _safe_str(tsb.get("summary", "")), chunk_id)
            )

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        return_connection(conn)


def count_extracted(data):
    """Total number of items extracted across all categories."""
    return sum(len(data.get(k, [])) for k in [
        "dtc_codes", "causes", "diagnostic_steps",
        "sensors", "tsb_references"
    ])


def process_document(doc_id):
    """Extract structured data from all relevant chunks of a document."""
    start_time = time.time()

    update_document_stage(doc_id, "extracting")
    log_processing(doc_id, "extracting", "started")

    # Fetch chunks, filtering by relevance_score >= 0.3 if evaluated
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT dc.id, dc.content
               FROM research.document_chunks dc
               LEFT JOIN research.chunk_evaluations ce
                   ON dc.id = ce.chunk_id
               WHERE dc.document_id = %s
                 AND (ce.relevance_score IS NULL
                      OR ce.relevance_score >= 0.3)
               ORDER BY dc.chunk_index""",
            (doc_id,)
        )
        chunks = cur.fetchall()
    finally:
        return_connection(conn)

    if not chunks:
        log_processing(doc_id, "extracting", "completed",
                       "No relevant chunks to process", 0)
        advance_to_next_stage(doc_id, "extracted", "resolving")
        return

    total_items = 0
    for chunk_id, content in chunks:
        prompt = (
            f"Extract all automotive technical data from this text:\n\n"
            f"---\n{content}\n---"
        )
        response_text = generate_completion(
            prompt=prompt,
            system_prompt=SYSTEM_PROMPT,
            format_json=True,
            temperature=0.1
        )

        data = parse_extraction(response_text)
        item_count = count_extracted(data)

        if item_count > 0:
            store_extraction(chunk_id, data)
            total_items += item_count

    duration_ms = int((time.time() - start_time) * 1000)
    log_processing(doc_id, "extracting", "completed",
                   f"Extracted {total_items} items", duration_ms)
    advance_to_next_stage(doc_id, "extracted", "resolving")
    print(f"[extraction] doc={doc_id} items={total_items} ms={duration_ms}")


def main():
    print(f"[extraction] Worker started. Queue={Config.WORKER_QUEUE} "
          f"Ollama={Config.OLLAMA_BASE_URL} Model={Config.REASONING_MODEL}")

    ensure_model_available(Config.REASONING_MODEL)

    while True:
        try:
            job = pop_job(Config.WORKER_QUEUE, timeout=Config.POLL_TIMEOUT)
            if job:
                process_document(job.strip())
        except Exception as e:
            print(f"[extraction] ERROR: {e}")
            traceback.print_exc()
            try:
                if job:
                    update_document_stage(job.strip(), "error", str(e)[:500])
                    log_processing(job.strip(), "extracting", "failed",
                                   str(e)[:500])
            except Exception:
                pass
        time.sleep(0.1)


if __name__ == "__main__":
    main()
