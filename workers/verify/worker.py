"""Verification worker: cross-verifies extracted DTC data using OpenAI API.

Picks unverified refined.dtc_codes records, sends data to OpenAI for
fact-checking, stores results, and adjusts confidence scores.

Queue: self-driven (no Redis queue, runs on timer)
"""
import sys
import os
import time
import traceback
import json

sys.path.insert(0, "/app")

from shared.db import execute_query, execute_query_one
from shared.openai_client import chat_completion, get_key_manager

VERIFY_INTERVAL = int(os.environ.get("VERIFY_INTERVAL", 30))
VERIFY_MODEL = os.environ.get("VERIFY_MODEL", "gpt-4o-mini")
BATCH_SIZE = int(os.environ.get("VERIFY_BATCH_SIZE", 5))


def get_unverified_code():
    """Fetch the next unverified DTC code with its related data.

    Returns:
        dict with code data or None if nothing to verify.
    """
    row = execute_query_one(
        """SELECT d.id, d.code, d.description, d.category, d.severity,
                  d.confidence_score, d.source_count
           FROM refined.dtc_codes d
           WHERE d.verified_at IS NULL
              OR d.verification_status = 'unverified'
           ORDER BY d.source_count DESC, d.confidence_score DESC
           LIMIT 1"""
    )
    if not row:
        return None

    dtc_id = str(row[0])
    code = row[1]

    causes = execute_query(
        """SELECT description, likelihood, confidence_score
           FROM refined.causes WHERE dtc_id = %s""",
        (dtc_id,), fetch=True,
    ) or []

    steps = execute_query(
        """SELECT step_order, description, tools_required, expected_values
           FROM refined.diagnostic_steps WHERE dtc_id = %s
           ORDER BY step_order""",
        (dtc_id,), fetch=True,
    ) or []

    sensors = execute_query(
        """SELECT name, sensor_type, typical_range, unit
           FROM refined.sensors WHERE %s = ANY(related_dtc_codes)""",
        (code,), fetch=True,
    ) or []

    return {
        "id": dtc_id,
        "code": code,
        "description": row[2],
        "category": row[3],
        "severity": row[4],
        "confidence_score": float(row[5]) if row[5] else 0.5,
        "source_count": row[6],
        "causes": [
            {"description": c[0], "likelihood": c[1],
             "confidence": float(c[2]) if c[2] else 0.5}
            for c in causes
        ],
        "diagnostic_steps": [
            {"order": s[0], "description": s[1],
             "tools": s[2], "expected": s[3]}
            for s in steps
        ],
        "sensors": [
            {"name": s[0], "type": s[1], "range": s[2], "unit": s[3]}
            for s in sensors
        ],
    }


def build_verification_prompt(dtc_data):
    """Build the OpenAI prompt for verifying DTC data."""
    data_summary = json.dumps({
        "code": dtc_data["code"],
        "description": dtc_data["description"],
        "category": dtc_data["category"],
        "severity": dtc_data["severity"],
        "causes": dtc_data["causes"],
        "diagnostic_steps": dtc_data["diagnostic_steps"],
        "sensors": dtc_data["sensors"],
    }, indent=2)

    return [
        {
            "role": "system",
            "content": (
                "You are an automotive diagnostics expert. You verify the accuracy "
                "of OBD-II diagnostic trouble code (DTC) information. Respond ONLY "
                "with a JSON object, no other text."
            ),
        },
        {
            "role": "user",
            "content": f"""Verify the following DTC code information for accuracy.

{data_summary}

For each field, assess whether it is:
- "confirmed": Accurate and complete
- "corrected": Has errors, provide the correction
- "disputed": Likely wrong or misleading
- "uncertain": Cannot determine accuracy

Respond with ONLY this JSON structure:
{{
    "code": "{dtc_data['code']}",
    "overall_accuracy": 0.0-1.0,
    "fields": {{
        "description": {{
            "result": "confirmed|corrected|disputed|uncertain",
            "notes": "explanation",
            "correction": "corrected value if applicable"
        }},
        "causes": {{
            "result": "confirmed|corrected|disputed|uncertain",
            "notes": "explanation",
            "missing_causes": ["any important causes not listed"]
        }},
        "diagnostic_steps": {{
            "result": "confirmed|corrected|disputed|uncertain",
            "notes": "explanation"
        }},
        "sensors": {{
            "result": "confirmed|corrected|disputed|uncertain",
            "notes": "explanation"
        }}
    }},
    "confidence_adjustment": -0.3 to +0.3
}}""",
        },
    ]


def parse_verification(response_text):
    """Parse verification JSON with fallback strategies."""
    text = response_text.strip()

    # Strategy 1: direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Strategy 2: extract from code block
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

    return None


def process_verification_result(dtc_data, verification, key_id, tokens_used):
    """Store verification results and adjust confidence scores."""
    dtc_id = dtc_data["id"]
    adjustment = verification.get("confidence_adjustment", 0.0)
    adjustment = max(-0.3, min(0.3, float(adjustment)))

    fields = verification.get("fields", {})

    for field_name, field_result in fields.items():
        result = field_result.get("result", "uncertain")
        execute_query(
            """INSERT INTO refined.verification_results
               (dtc_id, field_verified, original_value, verification_result,
                openai_response, confidence_adjustment, model_used,
                api_key_id, tokens_used)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                dtc_id,
                field_name,
                json.dumps(dtc_data.get(field_name, "")),
                result,
                json.dumps(field_result),
                adjustment if field_name == "description" else 0.0,
                VERIFY_MODEL,
                key_id,
                tokens_used // max(len(fields), 1),
            ),
        )

    # Determine overall verification status
    results = [f.get("result", "uncertain") for f in fields.values()]
    if all(r == "confirmed" for r in results):
        status = "verified"
    elif any(r == "disputed" for r in results):
        status = "disputed"
    elif any(r == "corrected" for r in results):
        status = "corrected"
    else:
        status = "uncertain"

    new_confidence = max(0.0, min(1.0,
                                   dtc_data["confidence_score"] + adjustment))

    execute_query(
        """UPDATE refined.dtc_codes
           SET verified_at = NOW(),
               verification_status = %s,
               verification_model = %s,
               pre_verification_confidence = confidence_score,
               confidence_score = %s
           WHERE id = %s""",
        (status, VERIFY_MODEL, new_confidence, dtc_id),
    )

    print(
        f"[verify] {dtc_data['code']}: status={status} "
        f"confidence={dtc_data['confidence_score']:.2f}->{new_confidence:.2f} "
        f"(adj={adjustment:+.2f}) key={key_id}"
    )


def verify_one():
    """Verify a single DTC code. Returns True if work was done."""
    dtc_data = get_unverified_code()
    if not dtc_data:
        return False

    mgr = get_key_manager()
    key_id, _ = mgr.get_best_key()
    if not key_id:
        print("[verify] No API keys available, waiting for rate limit reset")
        return False

    messages = build_verification_prompt(dtc_data)

    try:
        response_text, key_id, tokens_used = chat_completion(
            messages, model=VERIFY_MODEL, temperature=0.1, max_tokens=1500,
        )

        verification = parse_verification(response_text)
        if not verification:
            print(f"[verify] Failed to parse response for {dtc_data['code']}")
            return False

        process_verification_result(dtc_data, verification, key_id, tokens_used)
        return True

    except RuntimeError as e:
        print(f"[verify] {e}")
        return False
    except Exception as e:
        print(f"[verify] Error verifying {dtc_data['code']}: {e}")
        traceback.print_exc()
        return False


def log_key_stats():
    """Log API key usage stats."""
    mgr = get_key_manager()
    stats = mgr.get_all_key_stats()
    for key_id, s in stats.items():
        reset_in = max(0, s["rate_limit_reset"] - time.time())
        print(
            f"[verify] Key {key_id}: "
            f"requests={s['requests_made']} "
            f"tokens={s['tokens_used']} "
            f"remaining={s['rate_limit_remaining']} "
            f"reset_in={int(reset_in)}s"
        )


def main():
    print(f"[verify] Worker started. Model={VERIFY_MODEL}, "
          f"interval={VERIFY_INTERVAL}s")

    mgr = get_key_manager()
    print(f"[verify] Loaded {len(mgr.keys)} API key(s)")

    cycle = 0
    while True:
        try:
            did_work = verify_one()

            cycle += 1
            if cycle % 10 == 0:
                log_key_stats()

            if did_work:
                time.sleep(VERIFY_INTERVAL)
            else:
                time.sleep(VERIFY_INTERVAL * 4)

        except Exception as e:
            print(f"[verify] ERROR: {e}")
            traceback.print_exc()
            time.sleep(60)


if __name__ == "__main__":
    main()
