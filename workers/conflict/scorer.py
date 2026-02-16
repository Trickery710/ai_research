"""Deterministic scoring engine for DTC knowledge graph entities.

Computes a unified score S(entity, context) in [0, 100] for ranking
causes, fixes, parts, sensors, threads, steps, and symptoms.

S = EvidenceQualityScore + ConsensusScore + VehicleSpecificityScore + PracticalImpactScore
"""
import math
from typing import Optional


def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp value to [lo, hi]."""
    return max(lo, min(hi, float(value)))


def evidence_quality_score(avg_trust: float, avg_relevance: float) -> float:
    """Evidence Quality Score (0-50).

    quality = 0.65 * avg_trust + 0.35 * avg_relevance
    EQS = 50 * quality
    """
    quality = 0.65 * clamp(avg_trust) + 0.35 * clamp(avg_relevance)
    return 50.0 * quality


def consensus_score(evidence_count: int) -> float:
    """Consensus / Support Score (0-20).

    consensus = clamp(ln(1 + evidence_count) / ln(1 + 10), 0, 1)
    CS = 20 * consensus

    Examples: 1 -> ~6, 3 -> ~12, 10 -> 20
    """
    if evidence_count <= 0:
        return 0.0
    consensus = clamp(
        math.log(1 + evidence_count) / math.log(1 + 10), 0.0, 1.0
    )
    return 20.0 * consensus


def vehicle_specificity_score(
    entity_make_id: Optional[str],
    entity_model_id: Optional[str],
    entity_year_start: Optional[int],
    entity_year_end: Optional[int],
    ctx_make_id: Optional[str] = None,
    ctx_model_id: Optional[str] = None,
    ctx_year: Optional[int] = None,
) -> float:
    """Vehicle Specificity Score (-20 to +20).

    - Entity tied to make/model/year and matches context -> +20
    - Only make matches -> +12
    - OEM-agnostic (master-level, no make) -> +6
    - Conflicts with context (different make/model/year) -> -20
    """
    # No vehicle context provided: treat entity as neutral
    if not ctx_make_id:
        if not entity_make_id:
            return 6.0  # generic entity, no context
        return 6.0  # entity has vehicle info but no context to compare

    # Entity is OEM-agnostic (no make attached)
    if not entity_make_id:
        return 6.0

    # Entity has a make - check match
    if entity_make_id != ctx_make_id:
        return -20.0  # hard penalty: different make

    # Make matches
    if not ctx_model_id or not entity_model_id:
        return 12.0  # only make matches

    if entity_model_id != ctx_model_id:
        return -20.0  # different model for same make

    # Model matches - check year range
    if ctx_year and entity_year_start and entity_year_end:
        if entity_year_start <= ctx_year <= entity_year_end:
            return 20.0  # full match
        return -20.0  # year out of range
    if ctx_year and entity_year_start and not entity_year_end:
        if ctx_year >= entity_year_start:
            return 20.0
        return -20.0

    return 20.0  # make + model match, no year constraint


def practical_impact_score(
    entity_type: str,
    confirmed_repair_count: int = 0,
    probability_weight: float = 0.0,
    frequency_score: int = 0,
    solution_marked: bool = False,
) -> float:
    """Practical Impact Score (0-10).

    - fixes/parts: higher confirmed_repair_count -> higher score
    - causes: probability_weight directly
    - symptoms: frequency_score / 10
    - threads: solution_marked -> +6
    - steps/sensors/live_data: 0 (neutral)
    """
    if entity_type in ("fix", "part"):
        if confirmed_repair_count <= 0:
            return 0.0
        impact = clamp(
            math.log(1 + confirmed_repair_count) / math.log(1 + 50), 0.0, 1.0
        )
        return 10.0 * impact

    if entity_type == "cause":
        return 10.0 * clamp(probability_weight)

    if entity_type == "symptom":
        return 10.0 * clamp(frequency_score / 10.0)

    if entity_type == "thread":
        return 6.0 if solution_marked else 0.0

    # steps, sensors, live_data, explanation
    return 0.0


def compute_score(
    entity_type: str,
    avg_trust: float = 0.0,
    avg_relevance: float = 0.0,
    evidence_count: int = 0,
    entity_make_id: Optional[str] = None,
    entity_model_id: Optional[str] = None,
    entity_year_start: Optional[int] = None,
    entity_year_end: Optional[int] = None,
    ctx_make_id: Optional[str] = None,
    ctx_model_id: Optional[str] = None,
    ctx_year: Optional[int] = None,
    confirmed_repair_count: int = 0,
    probability_weight: float = 0.0,
    frequency_score: int = 0,
    solution_marked: bool = False,
) -> float:
    """Compute the unified score S in [0, 100].

    Sort descending by S, then evidence_count desc,
    then avg_trust desc, then avg_relevance desc,
    then uuid asc (stable tie-breaker).
    """
    eqs = evidence_quality_score(avg_trust, avg_relevance)
    cs = consensus_score(evidence_count)
    vss = vehicle_specificity_score(
        entity_make_id, entity_model_id,
        entity_year_start, entity_year_end,
        ctx_make_id, ctx_model_id, ctx_year,
    )
    pis = practical_impact_score(
        entity_type,
        confirmed_repair_count=confirmed_repair_count,
        probability_weight=probability_weight,
        frequency_score=frequency_score,
        solution_marked=solution_marked,
    )
    return clamp(eqs + cs + vss + pis, 0.0, 100.0)


def sort_key(entity: dict) -> tuple:
    """Return a sort key for deterministic ordering.

    Sorts by: score DESC, evidence_count DESC, avg_trust DESC,
    avg_relevance DESC, id ASC (stable tie-breaker).
    """
    return (
        -entity.get("score", 0.0),
        -entity.get("evidence_count", 0),
        -entity.get("avg_trust", 0.0),
        -entity.get("avg_relevance", 0.0),
        str(entity.get("id", "")),
    )
