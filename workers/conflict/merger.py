"""Entity merger and deduplicator for DTC knowledge graph.

Normalizes strings, detects duplicates, and merges candidates
representing the same underlying fact into canonical rows.
"""
import re
import unicodedata
from typing import List, Dict, Optional, Tuple


def normalize_text(text: str) -> str:
    """Normalize a string for deduplication comparison.

    - Lowercase
    - Strip leading/trailing whitespace
    - Collapse internal whitespace
    - Remove punctuation except hyphens
    - Unicode normalize (NFKD)
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)  # remove punctuation except hyphen
    text = re.sub(r'\s+', ' ', text)       # collapse whitespace
    return text


def group_duplicates(
    candidates: List[dict],
    text_field: str,
) -> Dict[str, List[dict]]:
    """Group candidates by normalized text field value.

    Returns dict mapping normalized text -> list of candidate dicts.
    """
    groups: Dict[str, List[dict]] = {}
    for c in candidates:
        key = normalize_text(str(c.get(text_field, "")))
        if not key:
            continue
        groups.setdefault(key, []).append(c)
    return groups


def merge_text_entities(
    candidates: List[dict],
    text_field: str,
    score_field: str = "score",
) -> Tuple[List[dict], List[dict]]:
    """Merge duplicate text-based entities, keeping the highest-scoring canonical row.

    Returns:
        (merged_canonical_list, rejected_list)

    For each group of duplicates:
    - Keep the candidate with the highest score as canonical
    - Aggregate evidence_count, avg_trust, avg_relevance from all members
    - Collect all source chunk_ids
    - Mark non-canonical as rejected
    """
    groups = group_duplicates(candidates, text_field)
    merged = []
    rejected = []

    for _norm_text, group in groups.items():
        if len(group) == 1:
            merged.append(group[0])
            continue

        # Sort by score desc, pick winner
        group.sort(key=lambda x: -x.get(score_field, 0.0))
        winner = dict(group[0])  # copy

        # Aggregate stats from all members
        total_evidence = sum(c.get("evidence_count", 0) for c in group)
        all_trust = [c.get("avg_trust", 0) for c in group if c.get("evidence_count", 0) > 0]
        all_relevance = [c.get("avg_relevance", 0) for c in group if c.get("evidence_count", 0) > 0]

        winner["evidence_count"] = total_evidence
        if all_trust:
            winner["avg_trust"] = sum(all_trust) / len(all_trust)
        if all_relevance:
            winner["avg_relevance"] = sum(all_relevance) / len(all_relevance)

        # Collect all source chunk_ids
        all_sources = []
        for c in group:
            all_sources.extend(c.get("source_chunk_ids", []))
        winner["source_chunk_ids"] = list(set(all_sources))

        merged.append(winner)

        # Mark losers as rejected
        for loser in group[1:]:
            loser["_rejected_reason"] = "duplicate_merged"
            loser["_merged_into"] = winner.get("id")
            rejected.append(loser)

    return merged, rejected


def merge_numeric_ranges(
    candidates: List[dict],
    value_fields: List[str],
    score_field: str = "score",
) -> Tuple[dict, bool]:
    """Merge numeric range entities (PIDs, costs, labor hours).

    Prefers values supported by higher EvidenceQualityScore.
    If multiple high-quality sources disagree, stores range envelope
    and sets conflict_flag=True.

    Returns:
        (merged_entity, conflict_flag)
    """
    if not candidates:
        return {}, False
    if len(candidates) == 1:
        return candidates[0], False

    candidates.sort(key=lambda x: -x.get(score_field, 0.0))
    winner = dict(candidates[0])
    conflict_flag = False

    for field in value_fields:
        values = []
        for c in candidates:
            v = c.get(field)
            if v is not None:
                try:
                    values.append(float(v))
                except (TypeError, ValueError):
                    pass

        if len(values) <= 1:
            continue

        # Check if top candidates disagree significantly (>20% difference)
        top_val = values[0]
        for v in values[1:]:
            if top_val == 0:
                if v != 0:
                    conflict_flag = True
                    break
            elif abs(v - top_val) / abs(top_val) > 0.2:
                conflict_flag = True
                break

        if conflict_flag and field.endswith("_min"):
            winner[field] = min(values)
        elif conflict_flag and field.endswith("_max"):
            winner[field] = max(values)

    winner["conflict_flag"] = conflict_flag
    return winner, conflict_flag


def build_resolution_entry(
    action: str,
    entity_table: str,
    entity_id: Optional[str],
    details: dict,
) -> dict:
    """Build a resolution log entry dict."""
    return {
        "action": action,
        "entity_table": entity_table,
        "entity_id": entity_id,
        "details": details,
    }
