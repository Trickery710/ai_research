"""Unit tests for the deterministic scoring engine and merger."""
import math
import unittest
from scorer import (
    clamp, evidence_quality_score, consensus_score,
    vehicle_specificity_score, practical_impact_score,
    compute_score, sort_key,
)
from merger import (
    normalize_text, group_duplicates, merge_text_entities,
    merge_numeric_ranges,
)


class TestClamp(unittest.TestCase):
    def test_within_range(self):
        self.assertEqual(clamp(0.5), 0.5)

    def test_below_range(self):
        self.assertEqual(clamp(-0.5), 0.0)

    def test_above_range(self):
        self.assertEqual(clamp(1.5), 1.0)

    def test_custom_range(self):
        self.assertEqual(clamp(50.0, 0.0, 100.0), 50.0)
        self.assertEqual(clamp(-10.0, 0.0, 100.0), 0.0)
        self.assertEqual(clamp(150.0, 0.0, 100.0), 100.0)


class TestEvidenceQualityScore(unittest.TestCase):
    def test_perfect_scores(self):
        score = evidence_quality_score(1.0, 1.0)
        self.assertAlmostEqual(score, 50.0, places=2)

    def test_zero_scores(self):
        score = evidence_quality_score(0.0, 0.0)
        self.assertAlmostEqual(score, 0.0, places=2)

    def test_mixed_scores(self):
        # 0.65 * 0.8 + 0.35 * 0.6 = 0.52 + 0.21 = 0.73
        score = evidence_quality_score(0.8, 0.6)
        self.assertAlmostEqual(score, 50.0 * 0.73, places=2)

    def test_trust_weighted_higher(self):
        # Trust matters more (0.65 weight) than relevance (0.35)
        score_high_trust = evidence_quality_score(0.9, 0.3)
        score_high_relevance = evidence_quality_score(0.3, 0.9)
        self.assertGreater(score_high_trust, score_high_relevance)


class TestConsensusScore(unittest.TestCase):
    def test_zero_evidence(self):
        self.assertAlmostEqual(consensus_score(0), 0.0)

    def test_one_evidence(self):
        expected = 20.0 * (math.log(2) / math.log(11))
        self.assertAlmostEqual(consensus_score(1), expected, places=2)

    def test_ten_evidence_max(self):
        self.assertAlmostEqual(consensus_score(10), 20.0, places=2)

    def test_above_ten_capped(self):
        # Should still be 20.0 due to clamp
        self.assertAlmostEqual(consensus_score(100), 20.0, places=2)

    def test_three_evidence(self):
        expected = 20.0 * (math.log(4) / math.log(11))
        self.assertAlmostEqual(consensus_score(3), expected, places=1)


class TestVehicleSpecificityScore(unittest.TestCase):
    def test_no_context_generic_entity(self):
        score = vehicle_specificity_score(None, None, None, None)
        self.assertEqual(score, 6.0)

    def test_make_matches(self):
        score = vehicle_specificity_score(
            "make1", None, None, None, "make1", None, None
        )
        self.assertEqual(score, 12.0)

    def test_full_match(self):
        score = vehicle_specificity_score(
            "make1", "model1", 2020, 2024,
            "make1", "model1", 2022
        )
        self.assertEqual(score, 20.0)

    def test_different_make_penalty(self):
        score = vehicle_specificity_score(
            "make1", None, None, None,
            "make2", None, None
        )
        self.assertEqual(score, -20.0)

    def test_year_out_of_range_penalty(self):
        score = vehicle_specificity_score(
            "make1", "model1", 2020, 2022,
            "make1", "model1", 2025
        )
        self.assertEqual(score, -20.0)


class TestPracticalImpactScore(unittest.TestCase):
    def test_fix_with_repairs(self):
        score = practical_impact_score("fix", confirmed_repair_count=50)
        self.assertAlmostEqual(score, 10.0, places=1)

    def test_fix_with_zero_repairs(self):
        score = practical_impact_score("fix", confirmed_repair_count=0)
        self.assertAlmostEqual(score, 0.0)

    def test_cause_with_weight(self):
        score = practical_impact_score("cause", probability_weight=0.8)
        self.assertAlmostEqual(score, 8.0, places=2)

    def test_symptom_with_frequency(self):
        score = practical_impact_score("symptom", frequency_score=7)
        self.assertAlmostEqual(score, 7.0, places=2)

    def test_thread_with_solution(self):
        score = practical_impact_score("thread", solution_marked=True)
        self.assertEqual(score, 6.0)

    def test_thread_without_solution(self):
        score = practical_impact_score("thread", solution_marked=False)
        self.assertEqual(score, 0.0)

    def test_step_neutral(self):
        score = practical_impact_score("step")
        self.assertEqual(score, 0.0)


class TestComputeScore(unittest.TestCase):
    def test_perfect_cause(self):
        score = compute_score(
            entity_type="cause",
            avg_trust=1.0, avg_relevance=1.0,
            evidence_count=10,
            probability_weight=1.0,
        )
        # EQS=50, CS=20, VSS=6 (generic), PIS=10 => 86
        self.assertAlmostEqual(score, 86.0, places=0)

    def test_score_clamped_to_100(self):
        score = compute_score(
            entity_type="cause",
            avg_trust=1.0, avg_relevance=1.0,
            evidence_count=100,
            probability_weight=1.0,
            entity_make_id="m1", entity_model_id="mod1",
            entity_year_start=2020, entity_year_end=2024,
            ctx_make_id="m1", ctx_model_id="mod1", ctx_year=2022,
        )
        # EQS=50, CS=20, VSS=20, PIS=10 => 100
        self.assertAlmostEqual(score, 100.0, places=0)

    def test_conflicting_vehicle_penalty(self):
        score = compute_score(
            entity_type="cause",
            avg_trust=0.8, avg_relevance=0.8,
            evidence_count=5,
            probability_weight=0.5,
            entity_make_id="toyota",
            ctx_make_id="ford",
        )
        # VSS = -20, should significantly lower the score
        self.assertLess(score, 50.0)

    def test_zero_everything(self):
        score = compute_score(
            entity_type="cause",
            avg_trust=0.0, avg_relevance=0.0,
            evidence_count=0,
        )
        # EQS=0, CS=0, VSS=6, PIS=0 => 6
        self.assertAlmostEqual(score, 6.0, places=0)


class TestSortKey(unittest.TestCase):
    def test_sorts_by_score_desc(self):
        entities = [
            {"id": "a", "score": 50.0, "evidence_count": 1,
             "avg_trust": 0.5, "avg_relevance": 0.5},
            {"id": "b", "score": 80.0, "evidence_count": 1,
             "avg_trust": 0.5, "avg_relevance": 0.5},
        ]
        sorted_entities = sorted(entities, key=sort_key)
        self.assertEqual(sorted_entities[0]["id"], "b")

    def test_tiebreak_by_evidence(self):
        entities = [
            {"id": "a", "score": 50.0, "evidence_count": 3,
             "avg_trust": 0.5, "avg_relevance": 0.5},
            {"id": "b", "score": 50.0, "evidence_count": 5,
             "avg_trust": 0.5, "avg_relevance": 0.5},
        ]
        sorted_entities = sorted(entities, key=sort_key)
        self.assertEqual(sorted_entities[0]["id"], "b")

    def test_tiebreak_by_uuid_asc(self):
        entities = [
            {"id": "zzz", "score": 50.0, "evidence_count": 1,
             "avg_trust": 0.5, "avg_relevance": 0.5},
            {"id": "aaa", "score": 50.0, "evidence_count": 1,
             "avg_trust": 0.5, "avg_relevance": 0.5},
        ]
        sorted_entities = sorted(entities, key=sort_key)
        self.assertEqual(sorted_entities[0]["id"], "aaa")


class TestNormalizeText(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(normalize_text("Hello World!"), "hello world")

    def test_whitespace(self):
        self.assertEqual(normalize_text("  foo   bar  "), "foo bar")

    def test_punctuation(self):
        self.assertEqual(normalize_text("O2 sensor (bank 1)"), "o2 sensor bank 1")

    def test_hyphen_preserved(self):
        self.assertEqual(normalize_text("pre-cat"), "pre-cat")

    def test_empty(self):
        self.assertEqual(normalize_text(""), "")


class TestGroupDuplicates(unittest.TestCase):
    def test_groups_by_normalized(self):
        candidates = [
            {"cause": "Bad Spark Plug", "score": 80},
            {"cause": "bad spark plug", "score": 60},
            {"cause": "Faulty coil", "score": 70},
        ]
        groups = group_duplicates(candidates, "cause")
        self.assertEqual(len(groups), 2)
        self.assertEqual(len(groups["bad spark plug"]), 2)
        self.assertEqual(len(groups["faulty coil"]), 1)


class TestMergeTextEntities(unittest.TestCase):
    def test_merges_duplicates(self):
        candidates = [
            {"id": "1", "cause": "Bad Spark Plug", "score": 80,
             "evidence_count": 3, "avg_trust": 0.8, "avg_relevance": 0.7,
             "source_chunk_ids": ["c1"]},
            {"id": "2", "cause": "bad spark plug!", "score": 60,
             "evidence_count": 2, "avg_trust": 0.6, "avg_relevance": 0.5,
             "source_chunk_ids": ["c2"]},
            {"id": "3", "cause": "Faulty coil", "score": 70,
             "evidence_count": 1, "avg_trust": 0.7, "avg_relevance": 0.6,
             "source_chunk_ids": ["c3"]},
        ]
        merged, rejected = merge_text_entities(candidates, "cause")
        self.assertEqual(len(merged), 2)
        self.assertEqual(len(rejected), 1)

        # Winner should have aggregated evidence
        spark_plug = [m for m in merged if "spark" in m["cause"].lower()][0]
        self.assertEqual(spark_plug["evidence_count"], 5)  # 3+2
        self.assertIn("c1", spark_plug["source_chunk_ids"])
        self.assertIn("c2", spark_plug["source_chunk_ids"])

    def test_no_duplicates(self):
        candidates = [
            {"id": "1", "cause": "A", "score": 80, "evidence_count": 1,
             "avg_trust": 0.8, "avg_relevance": 0.7, "source_chunk_ids": []},
            {"id": "2", "cause": "B", "score": 60, "evidence_count": 1,
             "avg_trust": 0.6, "avg_relevance": 0.5, "source_chunk_ids": []},
        ]
        merged, rejected = merge_text_entities(candidates, "cause")
        self.assertEqual(len(merged), 2)
        self.assertEqual(len(rejected), 0)


class TestMergeNumericRanges(unittest.TestCase):
    def test_no_conflict(self):
        candidates = [
            {"pid_name": "MAP", "normal_range_min": 20.0,
             "normal_range_max": 30.0, "score": 80},
            {"pid_name": "MAP", "normal_range_min": 21.0,
             "normal_range_max": 29.0, "score": 60},
        ]
        merged, conflict = merge_numeric_ranges(
            candidates, ["normal_range_min", "normal_range_max"]
        )
        self.assertFalse(conflict)

    def test_conflict_detected(self):
        candidates = [
            {"pid_name": "MAP", "normal_range_min": 20.0,
             "normal_range_max": 30.0, "score": 80},
            {"pid_name": "MAP", "normal_range_min": 50.0,
             "normal_range_max": 60.0, "score": 70},
        ]
        merged, conflict = merge_numeric_ranges(
            candidates, ["normal_range_min", "normal_range_max"]
        )
        self.assertTrue(conflict)
        # Should use envelope
        self.assertEqual(merged["normal_range_min"], 20.0)
        self.assertEqual(merged["normal_range_max"], 60.0)


if __name__ == "__main__":
    unittest.main()
