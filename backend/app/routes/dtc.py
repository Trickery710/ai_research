"""DTC code API endpoints.

GET /dtc         -- List all extracted DTC codes
GET /dtc/{code}  -- Get full detail for a specific DTC code including
                    causes, diagnostic steps, related sensors, TSBs,
                    and knowledge graph data (OEM variants, ranked
                    fixes/parts/sensors/threads, decision tree, AI explanation)
"""
import logging
from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional

from app.db import execute_query, execute_query_one
from app.models import DTCResponse, DTCDetailResponse

router = APIRouter()
logger = logging.getLogger(__name__)


def _knowledge_schema_exists() -> bool:
    """Check if knowledge schema tables exist."""
    try:
        row = execute_query_one(
            """SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'knowledge' AND table_name = 'dtc_master'
            )"""
        )
        return row and row.get("exists", False)
    except Exception:
        return False


@router.get("/dtc", response_model=List[DTCResponse])
def list_dtc_codes(
    category: str = None,
    min_confidence: float = 0.0,
    limit: int = 50,
    offset: int = 0
):
    """List DTC codes, optionally filtered by category and min confidence.

    Prefers knowledge.dtc_master if available, falls back to refined.dtc_codes.
    """
    use_knowledge = _knowledge_schema_exists()

    if use_knowledge:
        # Query from knowledge graph with computed confidence
        base_query = """
            SELECT dm.id::text, dm.code,
                   dm.generic_description AS description,
                   dm.system_category AS category,
                   CASE dm.severity_level
                       WHEN 1 THEN 'info' WHEN 2 THEN 'low'
                       WHEN 3 THEN 'medium' WHEN 4 THEN 'high'
                       WHEN 5 THEN 'critical' ELSE NULL
                   END AS severity,
                   COALESCE(ae.confidence_score, 0.5) AS confidence_score,
                   COALESCE(src.cnt, 0)::int AS source_count
            FROM knowledge.dtc_master dm
            LEFT JOIN knowledge.dtc_ai_explanations ae
                ON ae.dtc_master_id = dm.id
            LEFT JOIN (
                SELECT entity_id, COUNT(*) AS cnt
                FROM knowledge.dtc_entity_sources
                WHERE entity_table = 'knowledge.dtc_master'
                GROUP BY entity_id
            ) src ON src.entity_id = dm.id
        """
        if category:
            rows = execute_query(
                base_query + """
                WHERE dm.system_category = %s
                  AND COALESCE(ae.confidence_score, 0.5) >= %s
                ORDER BY dm.code LIMIT %s OFFSET %s""",
                (category, min_confidence, limit, offset), fetch=True
            )
        else:
            rows = execute_query(
                base_query + """
                WHERE COALESCE(ae.confidence_score, 0.5) >= %s
                ORDER BY dm.code LIMIT %s OFFSET %s""",
                (min_confidence, limit, offset), fetch=True
            )
    else:
        # Fallback to refined schema
        if category:
            rows = execute_query(
                """SELECT id, code, description, category, severity,
                          confidence_score, source_count
                   FROM refined.dtc_codes
                   WHERE category = %s AND confidence_score >= %s
                   ORDER BY code LIMIT %s OFFSET %s""",
                (category, min_confidence, limit, offset), fetch=True
            )
        else:
            rows = execute_query(
                """SELECT id, code, description, category, severity,
                          confidence_score, source_count
                   FROM refined.dtc_codes
                   WHERE confidence_score >= %s
                   ORDER BY code LIMIT %s OFFSET %s""",
                (min_confidence, limit, offset), fetch=True
            )

    return [DTCResponse(**row) for row in (rows or [])]


@router.get("/dtc/{code}", response_model=DTCDetailResponse)
def get_dtc_detail(
    code: str,
    make: Optional[str] = Query(None, description="Filter by vehicle make"),
    model: Optional[str] = Query(None, description="Filter by vehicle model"),
    year: Optional[int] = Query(None, description="Filter by vehicle year"),
):
    """Get comprehensive detail for a single DTC code.

    Includes knowledge graph data when available: OEM variants, ranked
    causes/fixes/parts/sensors/threads, diagnostic step decision tree,
    and AI explanation.
    """
    code = code.strip().upper()

    # Try knowledge schema first
    use_knowledge = _knowledge_schema_exists()

    # Always get from refined for backward compat
    dtc = execute_query_one(
        """SELECT id, code, description, category, severity,
                  confidence_score, source_count
           FROM refined.dtc_codes WHERE code = %s""",
        (code,)
    )
    if not dtc:
        raise HTTPException(
            status_code=404, detail=f"DTC code {code} not found"
        )

    dtc_id = dtc["id"]

    # Legacy data from refined schema
    causes = execute_query(
        """SELECT description, likelihood, confidence_score
           FROM refined.causes WHERE dtc_id = %s
           ORDER BY confidence_score DESC""",
        (dtc_id,), fetch=True
    ) or []

    steps = execute_query(
        """SELECT step_order, description, tools_required,
                  expected_values, confidence_score
           FROM refined.diagnostic_steps WHERE dtc_id = %s
           ORDER BY step_order""",
        (dtc_id,), fetch=True
    ) or []

    sensors = execute_query(
        """SELECT name, sensor_type, typical_range, unit
           FROM refined.sensors WHERE %s = ANY(related_dtc_codes)""",
        (code,), fetch=True
    ) or []

    tsbs = execute_query(
        """SELECT tsb_number, title, affected_models, summary
           FROM refined.tsb_references WHERE %s = ANY(related_dtc_codes)""",
        (code,), fetch=True
    ) or []

    # Knowledge graph enrichment
    kg_data = {}
    if use_knowledge:
        kg_data = _get_knowledge_graph_data(code, make, model, year)

    return DTCDetailResponse(
        **dtc,
        causes=causes,
        diagnostic_steps=steps,
        sensors=sensors,
        tsb_references=tsbs,
        **kg_data,
    )


def _get_knowledge_graph_data(
    code: str,
    make: Optional[str] = None,
    model: Optional[str] = None,
    year: Optional[int] = None,
) -> dict:
    """Fetch enriched data from the knowledge graph."""
    result = {}

    try:
        master = execute_query_one(
            "SELECT id FROM knowledge.dtc_master WHERE code = %s",
            (code,)
        )
        if not master:
            return result
        master_id = master["id"]

        # OEM Variants
        result["oem_variants"] = execute_query(
            """SELECT ov.oem_description, m.name AS make,
                      md.name AS model, ov.year_start, ov.year_end,
                      ov.tsb_reference, ov.known_pattern_failure
               FROM knowledge.dtc_oem_variant ov
               JOIN knowledge.makes m ON ov.make_id = m.id
               LEFT JOIN knowledge.models md ON ov.model_id = md.id
               WHERE ov.dtc_master_id = %s
               ORDER BY m.name, md.name""",
            (master_id,), fetch=True
        ) or []

        # Ranked Symptoms
        result["symptoms"] = execute_query(
            """SELECT symptom, frequency_score, evidence_count,
                      avg_trust, avg_relevance
               FROM knowledge.dtc_symptoms
               WHERE dtc_master_id = %s
               ORDER BY frequency_score DESC, evidence_count DESC""",
            (master_id,), fetch=True
        ) or []

        # Ranked Verified Fixes (with scoring)
        result["verified_fixes"] = execute_query(
            """SELECT f.fix_description, f.confirmed_repair_count,
                      f.average_cost, f.average_labor_hours,
                      f.evidence_count, f.avg_trust, f.avg_relevance,
                      m.name AS make, md.name AS model, f.engine_code
               FROM knowledge.dtc_verified_fixes f
               LEFT JOIN knowledge.makes m ON f.make_id = m.id
               LEFT JOIN knowledge.models md ON f.model_id = md.id
               WHERE f.dtc_master_id = %s
               ORDER BY f.confirmed_repair_count DESC,
                        f.avg_trust DESC""",
            (master_id,), fetch=True
        ) or []

        # Ranked Related Parts
        result["related_parts"] = execute_query(
            """SELECT p.name AS part_name, p.part_number,
                      rp.part_category, rp.priority_rank,
                      rp.evidence_count, rp.avg_trust, rp.avg_relevance
               FROM knowledge.dtc_related_parts rp
               JOIN knowledge.parts p ON rp.part_id = p.id
               WHERE rp.dtc_master_id = %s
               ORDER BY rp.priority_rank""",
            (master_id,), fetch=True
        ) or []

        # Forum Threads
        result["forum_threads"] = execute_query(
            """SELECT ft.title, ft.platform, ft.external_url,
                      dft.solution_marked, dft.evidence_count,
                      dft.avg_trust, dft.avg_relevance
               FROM knowledge.dtc_forum_threads dft
               JOIN knowledge.forum_threads ft ON dft.thread_id = ft.id
               WHERE dft.dtc_master_id = %s
               ORDER BY dft.solution_marked DESC,
                        dft.avg_trust DESC""",
            (master_id,), fetch=True
        ) or []

        # Live Data Parameters
        result["live_data_parameters"] = execute_query(
            """SELECT pid_name, normal_range_min, normal_range_max, unit,
                      evidence_count, avg_trust, avg_relevance
               FROM knowledge.dtc_live_data_parameters
               WHERE dtc_master_id = %s
               ORDER BY pid_name""",
            (master_id,), fetch=True
        ) or []

        # AI Explanation
        ai_row = execute_query_one(
            """SELECT explanation_simple, explanation_advanced,
                      diagnostic_strategy, confidence_score, model_used
               FROM knowledge.dtc_ai_explanations
               WHERE dtc_master_id = %s""",
            (master_id,)
        )
        if ai_row:
            result["ai_explanation"] = dict(ai_row)

    except Exception as e:
        logger.warning(f"Knowledge graph query failed for {code}: {e}")

    return result
