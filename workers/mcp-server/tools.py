"""MCP tool implementations for the automotive knowledge base."""
import sys
import json

sys.path.insert(0, "/app")

from shared.db import execute_query, execute_query_one
from shared.ollama_client import generate_embedding
from shared.config import Config


def lookup_dtc(code: str) -> dict:
    """Look up full details for a specific DTC code.

    Args:
        code: DTC code (e.g., "P0301").

    Returns:
        dict with code details, causes, diagnostic steps, sensors, TSBs.
    """
    # Get base DTC info
    dtc = execute_query_one(
        """SELECT id, code, description, category, severity,
                  confidence_score, source_count, first_seen, updated_at
        FROM refined.dtc_codes WHERE code = %s""",
        (code.upper(),)
    )

    if not dtc:
        return {"error": f"DTC code {code} not found"}

    dtc_id = dtc[0]

    # Get causes
    causes = execute_query(
        """SELECT description, likelihood, confidence_score
        FROM refined.causes WHERE dtc_id = %s
        ORDER BY confidence_score DESC""",
        (dtc_id,), fetch=True
    )

    # Get diagnostic steps
    steps = execute_query(
        """SELECT step_order, description, tools_required, expected_values,
                  confidence_score
        FROM refined.diagnostic_steps WHERE dtc_id = %s
        ORDER BY step_order""",
        (dtc_id,), fetch=True
    )

    # Get related sensors
    sensors = execute_query(
        """SELECT name, sensor_type, typical_range, unit, confidence_score
        FROM refined.sensors WHERE %s = ANY(related_dtc_codes)""",
        (code.upper(),), fetch=True
    )

    # Get TSB references
    tsbs = execute_query(
        """SELECT tsb_number, title, affected_models, summary, confidence_score
        FROM refined.tsb_references WHERE %s = ANY(related_dtc_codes)""",
        (code.upper(),), fetch=True
    )

    return {
        "code": dtc[1],
        "description": dtc[2],
        "category": dtc[3],
        "severity": dtc[4],
        "confidence_score": round(float(dtc[5]), 4),
        "source_count": dtc[6],
        "first_seen": str(dtc[7]),
        "updated_at": str(dtc[8]),
        "causes": [
            {"description": c[0], "likelihood": c[1],
             "confidence": round(float(c[2]), 4)}
            for c in (causes or [])
        ],
        "diagnostic_steps": [
            {"step": s[0], "description": s[1], "tools": s[2],
             "expected_values": s[3], "confidence": round(float(s[4]), 4)}
            for s in (steps or [])
        ],
        "sensors": [
            {"name": s[0], "type": s[1], "range": s[2],
             "unit": s[3], "confidence": round(float(s[4]), 4)}
            for s in (sensors or [])
        ],
        "tsb_references": [
            {"number": t[0], "title": t[1], "affected_models": t[2],
             "summary": t[3], "confidence": round(float(t[4]), 4)}
            for t in (tsbs or [])
        ],
    }


def search_knowledge(query: str, limit: int = 10,
                     min_trust: float = 0.0) -> list:
    """Semantic vector search across the knowledge base.

    Args:
        query: Natural language search query.
        limit: Max results to return.
        min_trust: Minimum trust score filter.

    Returns:
        List of matching chunks with metadata.
    """
    # Generate embedding for query
    try:
        embedding = generate_embedding(query)
    except Exception as e:
        return [{"error": f"Failed to generate embedding: {e}"}]

    embedding_str = str(embedding)

    rows = execute_query(
        """SELECT
            dc.id, dc.content, dc.document_id,
            d.title, d.source_url,
            ce.trust_score, ce.relevance_score,
            1 - (dc.embedding <=> %s::vector) AS similarity
        FROM research.document_chunks dc
        JOIN research.documents d ON dc.document_id = d.id
        LEFT JOIN research.chunk_evaluations ce ON dc.id = ce.chunk_id
        WHERE dc.embedding IS NOT NULL
            AND (ce.trust_score IS NULL OR ce.trust_score >= %s)
        ORDER BY dc.embedding <=> %s::vector
        LIMIT %s""",
        (embedding_str, min_trust, embedding_str, limit),
        fetch=True
    )

    return [
        {
            "chunk_id": str(r[0]),
            "content": r[1],
            "document_id": str(r[2]),
            "document_title": r[3],
            "source_url": r[4],
            "trust_score": round(float(r[5]), 4) if r[5] else None,
            "relevance_score": round(float(r[6]), 4) if r[6] else None,
            "similarity": round(float(r[7]), 4),
        }
        for r in (rows or [])
    ]


def list_dtc_codes(category: str = None, min_confidence: float = 0.0,
                   limit: int = 50) -> list:
    """List DTC codes with optional filtering.

    Args:
        category: Filter by category (e.g., "Powertrain").
        min_confidence: Minimum confidence score.
        limit: Max results.

    Returns:
        List of DTC code summaries.
    """
    if category:
        rows = execute_query(
            """SELECT code, description, category, severity,
                      confidence_score, source_count
            FROM refined.dtc_codes
            WHERE category = %s AND confidence_score >= %s
            ORDER BY code
            LIMIT %s""",
            (category, min_confidence, limit),
            fetch=True
        )
    else:
        rows = execute_query(
            """SELECT code, description, category, severity,
                      confidence_score, source_count
            FROM refined.dtc_codes
            WHERE confidence_score >= %s
            ORDER BY code
            LIMIT %s""",
            (min_confidence, limit),
            fetch=True
        )

    return [
        {
            "code": r[0],
            "description": r[1],
            "category": r[2],
            "severity": r[3],
            "confidence_score": round(float(r[4]), 4),
            "source_count": r[5],
        }
        for r in (rows or [])
    ]


def get_system_stats() -> dict:
    """Get knowledge base coverage and quality metrics.

    Returns:
        dict with comprehensive system statistics.
    """
    total_dtc = execute_query_one(
        "SELECT COUNT(*) FROM refined.dtc_codes"
    )
    total_docs = execute_query_one(
        "SELECT COUNT(*) FROM research.documents"
    )
    total_chunks = execute_query_one(
        "SELECT COUNT(*) FROM research.document_chunks"
    )
    avg_confidence = execute_query_one(
        "SELECT COALESCE(AVG(confidence_score), 0) FROM refined.dtc_codes"
    )

    # Category breakdown
    cat_rows = execute_query(
        """SELECT category, COUNT(*), AVG(confidence_score)
        FROM refined.dtc_codes
        GROUP BY category ORDER BY COUNT(*) DESC""",
        fetch=True
    )

    # Latest coverage snapshot
    snapshot = execute_query_one(
        """SELECT snapshot_date, total_dtc_codes, completeness_score
        FROM research.coverage_snapshots
        ORDER BY snapshot_date DESC LIMIT 1"""
    )

    return {
        "total_dtc_codes": total_dtc[0] if total_dtc else 0,
        "total_documents": total_docs[0] if total_docs else 0,
        "total_chunks": total_chunks[0] if total_chunks else 0,
        "avg_confidence": round(float(avg_confidence[0]), 4) if avg_confidence else 0,
        "by_category": {
            r[0] or "Unknown": {
                "count": r[1],
                "avg_confidence": round(float(r[2]), 4)
            }
            for r in (cat_rows or [])
        },
        "latest_snapshot": {
            "date": str(snapshot[0]),
            "total_codes": snapshot[1],
            "completeness": round(float(snapshot[2]), 4),
        } if snapshot else None,
    }
