"""Auditor worker: evaluates data quality, coverage gaps, and pipeline health.

Runs on a 30-minute timer and also accepts directives via the
orchestrator:audit Redis queue.
"""
import sys
import time
import traceback
import json

sys.path.insert(0, "/app")

from shared.config import Config
from shared.redis_client import get_redis, pop_job, push_job

AUDIT_QUEUE = "orchestrator:audit"
COMMAND_QUEUE = "orchestrator:commands"
AUDIT_INTERVAL = int(__import__("os").environ.get("AUDIT_INTERVAL", 1800))  # 30 min


def run_full_audit():
    """Execute a complete audit cycle: quality, coverage, pipeline."""
    from auditor.quality_analyzer import (
        analyze_confidence_distribution,
        compute_dtc_completeness,
        get_low_confidence_codes,
    )
    from auditor.coverage_analyzer import analyze_coverage, take_coverage_snapshot
    from auditor.pipeline_analyzer import get_pipeline_summary
    from auditor.report_generator import (
        generate_full_report,
        store_report,
        store_coverage_snapshot,
    )

    print("[auditor] Running full audit...")
    start = time.time()

    # Gather data from all analyzers
    confidence = analyze_confidence_distribution()
    completeness = compute_dtc_completeness()
    low_conf = get_low_confidence_codes(threshold=0.4)
    coverage = analyze_coverage()
    pipeline = get_pipeline_summary()

    quality_data = {
        "confidence": confidence,
        "completeness": completeness,
        "low_confidence_codes": low_conf,
    }

    # Generate and store report
    report = generate_full_report(quality_data, coverage, pipeline)
    report_id = store_report(report)

    # Take and store coverage snapshot
    try:
        snapshot = take_coverage_snapshot()
        store_coverage_snapshot(snapshot)
        print(f"[auditor] Coverage snapshot stored for {snapshot['snapshot_date']}")
    except Exception as e:
        print(f"[auditor] Warning: Failed to store coverage snapshot: {e}")

    duration_ms = int((time.time() - start) * 1000)
    print(
        f"[auditor] Audit complete in {duration_ms}ms. "
        f"Report={report_id}. "
        f"DTCs={confidence.get('total', 0)}, "
        f"Completeness={completeness.get('avg_completeness', 0):.1%}, "
        f"Gaps={len(coverage.get('gap_ranges', []))}, "
        f"Pipeline={pipeline.get('health', 'unknown')}"
    )

    # Push high-priority findings to orchestrator
    recommendations = report.get("recommendations", [])
    high_priority = [r for r in recommendations if r.get("priority", 99) <= 2]
    if high_priority:
        push_job(COMMAND_QUEUE, json.dumps({
            "source": "auditor",
            "type": "audit_findings",
            "report_id": report_id,
            "findings": high_priority,
        }))
        print(f"[auditor] Pushed {len(high_priority)} high-priority findings to orchestrator")

    return report_id


def handle_directive(directive_json):
    """Handle a directive from the orchestrator.

    Supported directive types:
      - full_audit: Run complete audit
      - quality_check: Run quality analysis only
      - coverage_check: Run coverage analysis only
      - pipeline_check: Run pipeline analysis only
    """
    try:
        directive = json.loads(directive_json)
    except json.JSONDecodeError:
        print(f"[auditor] Invalid directive JSON: {directive_json[:100]}")
        return

    dtype = directive.get("type", "full_audit")
    print(f"[auditor] Received directive: {dtype}")

    if dtype == "full_audit":
        run_full_audit()
    elif dtype == "quality_check":
        from auditor.quality_analyzer import analyze_confidence_distribution
        result = analyze_confidence_distribution()
        print(f"[auditor] Quality check: {result}")
    elif dtype == "coverage_check":
        from auditor.coverage_analyzer import analyze_coverage
        result = analyze_coverage()
        print(f"[auditor] Coverage check: {result.get('total_codes', 0)} codes")
    elif dtype == "pipeline_check":
        from auditor.pipeline_analyzer import get_pipeline_summary
        result = get_pipeline_summary()
        print(f"[auditor] Pipeline check: {result.get('health', 'unknown')}")
    else:
        print(f"[auditor] Unknown directive type: {dtype}")


def main():
    print(f"[auditor] Worker started. Interval={AUDIT_INTERVAL}s, Queue={AUDIT_QUEUE}")

    last_audit = 0

    while True:
        try:
            # Check for directives from orchestrator (non-blocking, short timeout)
            directive = pop_job(AUDIT_QUEUE, timeout=2)
            if directive:
                handle_directive(directive)
                continue

            # Timer-based full audit
            now = time.time()
            if now - last_audit >= AUDIT_INTERVAL:
                run_full_audit()
                last_audit = time.time()

        except Exception as e:
            print(f"[auditor] ERROR: {e}")
            traceback.print_exc()

        time.sleep(1)


if __name__ == "__main__":
    main()
