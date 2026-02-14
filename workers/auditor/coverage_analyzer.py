"""Analyzes DTC code coverage: range gaps, missing categories."""
import re
from shared.db import execute_query


# Known DTC code prefixes and expected ranges
DTC_PREFIXES = {
    "P0": {"start": 0, "end": 999, "category": "Powertrain (generic)"},
    "P1": {"start": 0, "end": 999, "category": "Powertrain (manufacturer)"},
    "P2": {"start": 0, "end": 999, "category": "Powertrain (generic ext)"},
    "P3": {"start": 0, "end": 499, "category": "Powertrain (reserved)"},
    "B0": {"start": 0, "end": 999, "category": "Body (generic)"},
    "B1": {"start": 0, "end": 999, "category": "Body (manufacturer)"},
    "C0": {"start": 0, "end": 999, "category": "Chassis (generic)"},
    "C1": {"start": 0, "end": 999, "category": "Chassis (manufacturer)"},
    "U0": {"start": 0, "end": 999, "category": "Network (generic)"},
    "U1": {"start": 0, "end": 999, "category": "Network (manufacturer)"},
}

# Approximate expected codes per hundred-range (e.g., P00xx should have ~40)
EXPECTED_DENSITY_PER_HUNDRED = 30


def analyze_coverage():
    """Analyze DTC code coverage and find gap ranges.

    Returns:
        dict with category breakdown, gap ranges, and summary stats.
    """
    rows = execute_query(
        "SELECT code FROM refined.dtc_codes ORDER BY code",
        fetch=True
    )

    existing_codes = set()
    for row in (rows or []):
        existing_codes.add(row[0])

    by_category = _categorize_codes(existing_codes)
    gap_ranges = _find_gap_ranges(existing_codes)

    return {
        "total_codes": len(existing_codes),
        "by_category": by_category,
        "gap_ranges": gap_ranges,
    }


def _categorize_codes(codes):
    """Group existing codes by their prefix category."""
    categories = {}
    for code in codes:
        if len(code) >= 2:
            prefix = code[0]
            # Map to high-level category
            if prefix == "P":
                cat = "Powertrain"
            elif prefix == "B":
                cat = "Body"
            elif prefix == "C":
                cat = "Chassis"
            elif prefix == "U":
                cat = "Network"
            else:
                cat = "Unknown"

            categories.setdefault(cat, 0)
            categories[cat] += 1

    return categories


def _find_gap_ranges(codes):
    """Detect hundred-ranges with very few codes (potential gaps).

    For example, if P02xx has only 2 codes but we'd expect ~30,
    that's a gap worth researching.
    """
    # Parse codes into prefix + number
    code_numbers = {}  # prefix -> list of numbers
    for code in codes:
        match = re.match(r'^([PBCU]\d)(\d{2,3})$', code)
        if match:
            prefix = match.group(1)
            num = int(match.group(2))
            code_numbers.setdefault(prefix, []).append(num)

    gaps = []
    for prefix, info in DTC_PREFIXES.items():
        numbers = set(code_numbers.get(prefix, []))
        if not numbers:
            continue  # Skip prefixes with zero codes (not started)

        # Check each hundred-range
        max_range = min(info["end"], 999)
        for hundred_start in range(0, max_range + 1, 100):
            hundred_end = min(hundred_start + 99, max_range)
            count_in_range = sum(
                1 for n in numbers if hundred_start <= n <= hundred_end
            )

            # Only flag if we have SOME codes in this prefix but this range is sparse
            if count_in_range < 5 and len(numbers) > 10:
                range_label = f"{prefix}{hundred_start:02d}-{prefix}{hundred_end:02d}"
                gaps.append({
                    "range": range_label,
                    "prefix": prefix,
                    "category": info["category"],
                    "existing_count": count_in_range,
                    "expected_min": EXPECTED_DENSITY_PER_HUNDRED,
                    "priority": "high" if count_in_range == 0 else "medium",
                })

    # Sort by priority (high first), then by range
    gaps.sort(key=lambda g: (0 if g["priority"] == "high" else 1, g["range"]))
    return gaps[:30]  # Top 30 gaps


def get_missing_dtc_codes_in_range(prefix, start, end):
    """List specific DTC codes missing in a range.

    Args:
        prefix: e.g. "P0"
        start: e.g. 100
        end: e.g. 199

    Returns:
        List of missing code strings.
    """
    rows = execute_query(
        "SELECT code FROM refined.dtc_codes WHERE code LIKE %s ORDER BY code",
        (f"{prefix}%",),
        fetch=True
    )

    existing = set(r[0] for r in (rows or []))
    missing = []
    for num in range(start, end + 1):
        code = f"{prefix}{num:03d}" if num < 100 else f"{prefix}{num}"
        if code not in existing:
            missing.append(code)

    return missing


def take_coverage_snapshot():
    """Create a coverage snapshot for the current date.

    Returns:
        dict with snapshot data suitable for storing in coverage_snapshots table.
    """
    from datetime import date

    coverage = analyze_coverage()

    # Compute confidence tier breakdown
    conf_rows = execute_query(
        """SELECT
            COUNT(*) FILTER (WHERE confidence_score < 0.3) AS low,
            COUNT(*) FILTER (WHERE confidence_score >= 0.3 AND confidence_score < 0.7) AS medium,
            COUNT(*) FILTER (WHERE confidence_score >= 0.7) AS high
        FROM refined.dtc_codes""",
        fetch=True
    )

    by_confidence = {"low": 0, "medium": 0, "high": 0}
    if conf_rows and conf_rows[0]:
        by_confidence = {
            "low": conf_rows[0][0],
            "medium": conf_rows[0][1],
            "high": conf_rows[0][2],
        }

    # Compute overall completeness from quality analyzer
    from auditor.quality_analyzer import compute_dtc_completeness
    completeness = compute_dtc_completeness()

    return {
        "snapshot_date": date.today().isoformat(),
        "total_dtc_codes": coverage["total_codes"],
        "by_category": coverage["by_category"],
        "by_confidence_tier": by_confidence,
        "gap_ranges": coverage["gap_ranges"],
        "completeness_score": completeness["avg_completeness"],
    }
