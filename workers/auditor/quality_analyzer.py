"""Analyzes data quality: confidence distributions, completeness per DTC."""
from shared.db import execute_query, execute_query_one


# Completeness weights for each DTC attribute
COMPLETENESS_WEIGHTS = {
    "has_description": 0.15,
    "has_category": 0.05,
    "has_severity": 0.05,
    "has_causes": 0.25,
    "has_diagnostic_steps": 0.30,
    "has_sensors": 0.10,
    "has_tsb": 0.10,
}


def analyze_confidence_distribution():
    """Get confidence score distribution across all DTC codes."""
    rows = execute_query(
        """SELECT
            COUNT(*) FILTER (WHERE confidence_score < 0.2) AS very_low,
            COUNT(*) FILTER (WHERE confidence_score >= 0.2 AND confidence_score < 0.4) AS low,
            COUNT(*) FILTER (WHERE confidence_score >= 0.4 AND confidence_score < 0.6) AS medium,
            COUNT(*) FILTER (WHERE confidence_score >= 0.6 AND confidence_score < 0.8) AS high,
            COUNT(*) FILTER (WHERE confidence_score >= 0.8) AS very_high,
            COUNT(*) AS total,
            COALESCE(AVG(confidence_score), 0) AS avg_confidence
        FROM refined.dtc_codes""",
        fetch=True
    )
    if not rows:
        return {"total": 0, "avg_confidence": 0, "distribution": {}}

    row = rows[0]
    return {
        "total": row[6],
        "avg_confidence": round(float(row[5]), 4),
        "distribution": {
            "very_low_0_20": row[0],
            "low_20_40": row[1],
            "medium_40_60": row[2],
            "high_60_80": row[3],
            "very_high_80_100": row[4],
        }
    }


def compute_dtc_completeness():
    """Compute completeness score for each DTC code.

    Returns:
        dict with summary stats and list of incomplete DTCs.
    """
    rows = execute_query(
        """SELECT
            d.id, d.code, d.description, d.category, d.severity,
            d.confidence_score,
            (SELECT COUNT(*) FROM refined.causes c WHERE c.dtc_id = d.id) AS cause_count,
            (SELECT COUNT(*) FROM refined.diagnostic_steps ds WHERE ds.dtc_id = d.id) AS step_count,
            (SELECT COUNT(*) FROM refined.sensors s WHERE d.code = ANY(s.related_dtc_codes)) AS sensor_count,
            (SELECT COUNT(*) FROM refined.tsb_references t WHERE d.code = ANY(t.related_dtc_codes)) AS tsb_count
        FROM refined.dtc_codes d
        ORDER BY d.code""",
        fetch=True
    )

    if not rows:
        return {
            "total_dtc_codes": 0,
            "complete_count": 0,
            "incomplete_count": 0,
            "avg_completeness": 0,
            "lowest_completeness": [],
        }

    completeness_scores = []
    incomplete = []

    for row in rows:
        dtc_id, code, desc, cat, sev, conf, causes, steps, sensors, tsbs = row

        score = 0.0
        if desc:
            score += COMPLETENESS_WEIGHTS["has_description"]
        if cat:
            score += COMPLETENESS_WEIGHTS["has_category"]
        if sev:
            score += COMPLETENESS_WEIGHTS["has_severity"]
        if causes and causes > 0:
            score += COMPLETENESS_WEIGHTS["has_causes"]
        if steps and steps > 0:
            score += COMPLETENESS_WEIGHTS["has_diagnostic_steps"]
        if sensors and sensors > 0:
            score += COMPLETENESS_WEIGHTS["has_sensors"]
        if tsbs and tsbs > 0:
            score += COMPLETENESS_WEIGHTS["has_tsb"]

        completeness_scores.append(score)
        if score < 1.0:
            incomplete.append({
                "code": code,
                "completeness": round(score, 2),
                "confidence": round(float(conf), 2),
                "missing": _identify_missing(desc, cat, sev, causes, steps, sensors, tsbs),
            })

    avg = sum(completeness_scores) / len(completeness_scores) if completeness_scores else 0
    complete_count = sum(1 for s in completeness_scores if s >= 1.0)

    # Sort incomplete by completeness ascending, return worst 20
    incomplete.sort(key=lambda x: x["completeness"])

    return {
        "total_dtc_codes": len(rows),
        "complete_count": complete_count,
        "incomplete_count": len(incomplete),
        "avg_completeness": round(avg, 4),
        "lowest_completeness": incomplete[:20],
    }


def _identify_missing(desc, cat, sev, causes, steps, sensors, tsbs):
    """Return list of missing attributes for a DTC code."""
    missing = []
    if not desc:
        missing.append("description")
    if not cat:
        missing.append("category")
    if not sev:
        missing.append("severity")
    if not causes or causes == 0:
        missing.append("causes")
    if not steps or steps == 0:
        missing.append("diagnostic_steps")
    if not sensors or sensors == 0:
        missing.append("sensors")
    if not tsbs or tsbs == 0:
        missing.append("tsb_references")
    return missing


def get_low_confidence_codes(threshold=0.4, limit=50):
    """Return DTC codes with confidence below threshold."""
    rows = execute_query(
        """SELECT code, description, confidence_score, source_count
        FROM refined.dtc_codes
        WHERE confidence_score < %s
        ORDER BY confidence_score ASC
        LIMIT %s""",
        (threshold, limit),
        fetch=True
    )
    return [
        {
            "code": r[0],
            "description": r[1],
            "confidence_score": round(float(r[2]), 4),
            "source_count": r[3],
        }
        for r in (rows or [])
    ]
