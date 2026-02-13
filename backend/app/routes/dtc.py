"""DTC code API endpoints.

GET /dtc         -- List all extracted DTC codes
GET /dtc/{code}  -- Get full detail for a specific DTC code including
                    causes, diagnostic steps, related sensors, and TSBs
"""
from fastapi import APIRouter, HTTPException
from typing import List

from app.db import execute_query, execute_query_one
from app.models import DTCResponse, DTCDetailResponse

router = APIRouter()


@router.get("/dtc", response_model=List[DTCResponse])
def list_dtc_codes(
    category: str = None,
    min_confidence: float = 0.0,
    limit: int = 50,
    offset: int = 0
):
    """List DTC codes, optionally filtered by category and min confidence."""
    if category:
        rows = execute_query(
            """SELECT id, code, description, category, severity,
                      confidence_score, source_count
               FROM refined.dtc_codes
               WHERE category = %s AND confidence_score >= %s
               ORDER BY code
               LIMIT %s OFFSET %s""",
            (category, min_confidence, limit, offset), fetch=True
        )
    else:
        rows = execute_query(
            """SELECT id, code, description, category, severity,
                      confidence_score, source_count
               FROM refined.dtc_codes
               WHERE confidence_score >= %s
               ORDER BY code
               LIMIT %s OFFSET %s""",
            (min_confidence, limit, offset), fetch=True
        )
    return [DTCResponse(**row) for row in (rows or [])]


@router.get("/dtc/{code}", response_model=DTCDetailResponse)
def get_dtc_detail(code: str):
    """Get comprehensive detail for a single DTC code."""
    code = code.strip().upper()

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

    causes = execute_query(
        """SELECT description, likelihood, confidence_score
           FROM refined.causes
           WHERE dtc_id = %s
           ORDER BY confidence_score DESC""",
        (dtc_id,), fetch=True
    ) or []

    steps = execute_query(
        """SELECT step_order, description, tools_required,
                  expected_values, confidence_score
           FROM refined.diagnostic_steps
           WHERE dtc_id = %s
           ORDER BY step_order""",
        (dtc_id,), fetch=True
    ) or []

    sensors = execute_query(
        """SELECT name, sensor_type, typical_range, unit
           FROM refined.sensors
           WHERE %s = ANY(related_dtc_codes)""",
        (code,), fetch=True
    ) or []

    tsbs = execute_query(
        """SELECT tsb_number, title, affected_models, summary
           FROM refined.tsb_references
           WHERE %s = ANY(related_dtc_codes)""",
        (code,), fetch=True
    ) or []

    return DTCDetailResponse(
        **dtc,
        causes=causes,
        diagnostic_steps=steps,
        sensors=sensors,
        tsb_references=tsbs
    )
