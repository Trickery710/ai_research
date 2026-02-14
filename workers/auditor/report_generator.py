"""Generates audit reports and stores them in the database."""
import json
from datetime import date
from shared.db import execute_query, execute_query_one


def generate_full_report(quality_data, coverage_data, pipeline_data):
    """Generate a comprehensive audit report from analyzer outputs.

    Args:
        quality_data: Output from quality_analyzer functions.
        coverage_data: Output from coverage_analyzer.analyze_coverage().
        pipeline_data: Output from pipeline_analyzer.get_pipeline_summary().

    Returns:
        dict with report data.
    """
    recommendations = _generate_recommendations(
        quality_data, coverage_data, pipeline_data
    )

    metrics = {
        "quality": quality_data,
        "coverage": coverage_data,
        "pipeline": pipeline_data,
    }

    summary_parts = []

    # Quality summary
    conf = quality_data.get("confidence", {})
    if conf.get("total", 0) > 0:
        summary_parts.append(
            f"Knowledge base has {conf['total']} DTC codes with "
            f"avg confidence {conf.get('avg_confidence', 0):.2f}."
        )

    # Completeness summary
    comp = quality_data.get("completeness", {})
    if comp.get("total_dtc_codes", 0) > 0:
        summary_parts.append(
            f"{comp['complete_count']}/{comp['total_dtc_codes']} codes fully complete "
            f"(avg completeness {comp.get('avg_completeness', 0):.1%})."
        )

    # Coverage summary
    gaps = coverage_data.get("gap_ranges", [])
    if gaps:
        high_priority = sum(1 for g in gaps if g.get("priority") == "high")
        summary_parts.append(
            f"Found {len(gaps)} coverage gaps ({high_priority} high priority)."
        )

    # Pipeline summary
    health = pipeline_data.get("health", "unknown")
    summary_parts.append(f"Pipeline health: {health}.")
    if pipeline_data.get("issues"):
        summary_parts.append(
            f"Issues: {'; '.join(pipeline_data['issues'][:3])}."
        )

    summary = " ".join(summary_parts)

    return {
        "report_type": "full_audit",
        "summary": summary,
        "metrics": metrics,
        "recommendations": recommendations,
    }


def _generate_recommendations(quality_data, coverage_data, pipeline_data):
    """Generate actionable recommendations based on audit findings."""
    recs = []

    # Quality recommendations
    low_conf = quality_data.get("low_confidence_codes", [])
    if low_conf:
        codes = [c["code"] for c in low_conf[:5]]
        recs.append({
            "type": "improve_confidence",
            "priority": 5,
            "description": f"Research more sources for low-confidence codes: {', '.join(codes)}",
            "target_codes": codes,
        })

    comp = quality_data.get("completeness", {})
    if comp.get("incomplete_count", 0) > 0:
        worst = comp.get("lowest_completeness", [])[:5]
        codes = [c["code"] for c in worst]
        recs.append({
            "type": "fill_gaps",
            "priority": 4,
            "description": f"Fill missing data for incomplete codes: {', '.join(codes)}",
            "target_codes": codes,
        })

    # Coverage recommendations
    gaps = coverage_data.get("gap_ranges", [])
    high_gaps = [g for g in gaps if g.get("priority") == "high"]
    if high_gaps:
        recs.append({
            "type": "expand_coverage",
            "priority": 6,
            "description": f"Research {len(high_gaps)} empty code ranges: "
                          f"{', '.join(g['range'] for g in high_gaps[:3])}",
            "target_ranges": [g["range"] for g in high_gaps[:10]],
        })

    # Pipeline recommendations
    pipeline_health = pipeline_data.get("health", "unknown")
    if pipeline_health == "degraded":
        recs.append({
            "type": "fix_pipeline",
            "priority": 1,
            "description": f"Pipeline degraded: {'; '.join(pipeline_data.get('issues', [])[:2])}",
        })

    stuck = pipeline_data.get("errors", {}).get("stuck_count", 0)
    if stuck > 0:
        recs.append({
            "type": "reprocess_errors",
            "priority": 2,
            "description": f"Reprocess {stuck} documents stuck in error state",
        })

    # Sort by priority (lower = higher priority)
    recs.sort(key=lambda r: r["priority"])
    return recs


def store_report(report):
    """Store an audit report in the database.

    Args:
        report: dict with report_type, summary, metrics, recommendations.

    Returns:
        UUID string of the created report.
    """
    row = execute_query_one(
        """INSERT INTO research.audit_reports
           (report_type, summary, metrics, recommendations)
           VALUES (%s, %s, %s, %s)
           RETURNING id""",
        (
            report["report_type"],
            report["summary"],
            json.dumps(report["metrics"]),
            json.dumps(report["recommendations"]),
        )
    )
    return str(row[0]) if row else None


def store_coverage_snapshot(snapshot):
    """Store a coverage snapshot, upserting by date.

    Args:
        snapshot: dict from coverage_analyzer.take_coverage_snapshot().
    """
    execute_query(
        """INSERT INTO research.coverage_snapshots
           (snapshot_date, total_dtc_codes, by_category,
            by_confidence_tier, gap_ranges, completeness_score)
           VALUES (%s, %s, %s, %s, %s, %s)
           ON CONFLICT (snapshot_date) DO UPDATE SET
            total_dtc_codes = EXCLUDED.total_dtc_codes,
            by_category = EXCLUDED.by_category,
            by_confidence_tier = EXCLUDED.by_confidence_tier,
            gap_ranges = EXCLUDED.gap_ranges,
            completeness_score = EXCLUDED.completeness_score""",
        (
            snapshot["snapshot_date"],
            snapshot["total_dtc_codes"],
            json.dumps(snapshot["by_category"]),
            json.dumps(snapshot["by_confidence_tier"]),
            json.dumps(snapshot["gap_ranges"]),
            snapshot["completeness_score"],
        )
    )
