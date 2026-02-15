"""LLM-driven gap analysis for the DTC knowledge base.

Instead of rigid rules, this module gathers a snapshot of the database state
and asks the reasoning model to decide what to research next and what search
queries to use. The LLM sees coverage stats, weak spots, and recent activity,
then returns prioritized search queries ready for SearXNG.
"""
import sys
import os
import json

sys.path.insert(0, "/app")

from shared.db import execute_query
from shared.ollama_client import generate_completion

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://llm-reason:11434")
REASONING_MODEL = os.environ.get("REASONING_MODEL", "mistral")


def get_db_snapshot():
    """Gather a compact snapshot of the knowledge base state for the LLM.

    Returns:
        dict with coverage stats, weak codes, gaps, and recent activity.
    """
    snapshot = {}

    # Overall stats
    row = execute_query(
        """SELECT COUNT(*),
                  ROUND(AVG(confidence_score)::numeric, 2),
                  ROUND(MIN(confidence_score)::numeric, 2),
                  SUM(source_count)
           FROM refined.dtc_codes""",
        fetch=True,
    )
    if row and row[0]:
        snapshot["total_codes"] = row[0][0] or 0
        snapshot["avg_confidence"] = float(row[0][1] or 0)
        snapshot["min_confidence"] = float(row[0][2] or 0)
        snapshot["total_sources"] = row[0][3] or 0
    else:
        snapshot["total_codes"] = 0
        snapshot["avg_confidence"] = 0
        snapshot["min_confidence"] = 0
        snapshot["total_sources"] = 0

    # Coverage by prefix (P0xxx, P1xxx, etc.)
    rows = execute_query(
        """SELECT LEFT(code, 2) AS prefix, COUNT(*),
                  ROUND(AVG(confidence_score)::numeric, 2)
           FROM refined.dtc_codes
           GROUP BY prefix ORDER BY prefix""",
        fetch=True,
    ) or []
    snapshot["coverage_by_prefix"] = {
        r[0]: {"count": r[1], "avg_confidence": float(r[2])}
        for r in rows
    }

    # Top 10 weakest codes (low confidence + few sources)
    rows = execute_query(
        """SELECT d.code, d.description, d.confidence_score, d.source_count,
                  (SELECT COUNT(*) FROM refined.causes c WHERE c.dtc_id = d.id) AS causes,
                  (SELECT COUNT(*) FROM refined.diagnostic_steps ds WHERE ds.dtc_id = d.id) AS steps
           FROM refined.dtc_codes d
           ORDER BY d.confidence_score ASC, d.source_count ASC
           LIMIT 10""",
        fetch=True,
    ) or []
    snapshot["weakest_codes"] = [
        {
            "code": r[0], "description": r[1] or "unknown",
            "confidence": float(r[2]), "sources": r[3],
            "causes": r[4], "steps": r[5],
        }
        for r in rows
    ]

    # Codes with missing data (have code but no causes or steps)
    rows = execute_query(
        """SELECT d.code, d.description,
                  (SELECT COUNT(*) FROM refined.causes c WHERE c.dtc_id = d.id) AS causes,
                  (SELECT COUNT(*) FROM refined.diagnostic_steps ds WHERE ds.dtc_id = d.id) AS steps
           FROM refined.dtc_codes d
           WHERE (SELECT COUNT(*) FROM refined.causes c WHERE c.dtc_id = d.id) = 0
              OR (SELECT COUNT(*) FROM refined.diagnostic_steps ds WHERE ds.dtc_id = d.id) = 0
           ORDER BY d.source_count DESC
           LIMIT 10""",
        fetch=True,
    ) or []
    snapshot["incomplete_codes"] = [
        {
            "code": r[0], "description": r[1] or "unknown",
            "has_causes": r[2] > 0, "has_steps": r[3] > 0,
        }
        for r in rows
    ]

    # Recently researched codes (avoid duplicating effort)
    rows = execute_query(
        """SELECT url FROM research.crawl_queue
           WHERE created_at > NOW() - INTERVAL '6 hours'
           ORDER BY created_at DESC
           LIMIT 15""",
        fetch=True,
    ) or []
    snapshot["recent_urls"] = [r[0] for r in rows]

    # Pipeline status
    row = execute_query(
        """SELECT
              (SELECT COUNT(*) FROM research.crawl_queue WHERE status = 'pending') AS pending_crawls,
              (SELECT COUNT(*) FROM research.documents WHERE processing_stage NOT IN ('complete', 'error')) AS in_pipeline""",
        fetch=True,
    )
    if row and row[0]:
        snapshot["pending_crawls"] = row[0][0] or 0
        snapshot["in_pipeline"] = row[0][1] or 0
    else:
        snapshot["pending_crawls"] = 0
        snapshot["in_pipeline"] = 0

    # Verified vs unverified
    rows = execute_query(
        """SELECT verification_status, COUNT(*)
           FROM refined.dtc_codes
           GROUP BY verification_status""",
        fetch=True,
    ) or []
    snapshot["verification"] = {r[0] or "unverified": r[1] for r in rows}

    return snapshot


def ask_llm_for_research_plan(snapshot):
    """Ask the reasoning model to analyze the DB snapshot and decide what to research.

    Returns:
        dict with "searches" list - each item has "query" and "reason".
        Returns None on failure.
    """
    snapshot_json = json.dumps(snapshot, indent=2, default=str)

    prompt = f"""You are the research strategist for an automotive DTC (diagnostic trouble code) knowledge base.

Here is the current state of the database:

{snapshot_json}

Your job: decide what to research next. You have access to a web search engine.
Generate 3-8 specific search queries that will find the most valuable new information.

Consider:
- Codes with LOW confidence or FEW sources need more data (search for those specific codes)
- Codes MISSING causes or diagnostic steps need targeted searches (e.g., "P0301 causes and diagnosis")
- If coverage is thin for certain prefixes, search for common codes in those ranges
- Avoid searching for things already in recent_urls
- If the pipeline already has many pending crawls, suggest fewer searches
- Think about what a mechanic would actually need: symptoms, causes, step-by-step diagnosis, sensor readings, common fixes
- Include varied search queries: some for specific codes, some for broader topics like "common transmission DTCs" or "OBD2 sensor specifications"

Respond with ONLY a JSON object:
{{
    "reasoning": "brief analysis of what the DB needs most",
    "searches": [
        {{
            "query": "the exact search query to use",
            "reason": "why this search is valuable",
            "target_codes": ["P0301"]
        }},
        ...
    ]
}}"""

    try:
        response = generate_completion(
            prompt,
            model=REASONING_MODEL,
            base_url=OLLAMA_BASE_URL,
            temperature=0.4,
            format_json=True,
        )

        result = json.loads(response)
        searches = result.get("searches", [])
        reasoning = result.get("reasoning", "")

        if reasoning:
            print(f"[gap_analyzer] LLM reasoning: {reasoning[:200]}")

        # Validate each search has a query string
        valid = [s for s in searches if isinstance(s.get("query"), str) and s["query"]]
        return {"reasoning": reasoning, "searches": valid}

    except json.JSONDecodeError:
        # Try to extract JSON from response
        try:
            first = response.find("{")
            last = response.rfind("}")
            if first != -1 and last > first:
                result = json.loads(response[first:last + 1])
                searches = result.get("searches", [])
                valid = [s for s in searches if isinstance(s.get("query"), str)]
                return {"reasoning": result.get("reasoning", ""), "searches": valid}
        except (json.JSONDecodeError, UnboundLocalError):
            pass
        print("[gap_analyzer] Failed to parse LLM response")
        return None

    except Exception as e:
        print(f"[gap_analyzer] LLM research planning failed: {e}")
        return None


def get_research_plan():
    """Main entry point: gather DB state and ask LLM what to research.

    Returns:
        list of search dicts [{"query": str, "reason": str, "target_codes": list}]
        or empty list on failure.
    """
    snapshot = get_db_snapshot()
    plan = ask_llm_for_research_plan(snapshot)

    if plan and plan.get("searches"):
        return plan["searches"]

    # Fallback: if LLM fails, return basic searches for weakest codes
    if snapshot.get("weakest_codes"):
        return [
            {
                "query": f"{code['code']} diagnostic trouble code causes diagnosis",
                "reason": f"fallback: low confidence ({code['confidence']})",
                "target_codes": [code["code"]],
            }
            for code in snapshot["weakest_codes"][:3]
        ]

    return []
