"""Transactional upserter for DTC knowledge graph tables.

Reads extracted data from refined.* tables and chunk_evaluations,
runs scoring and merging, then upserts into knowledge.* tables
with full provenance tracking.
"""
import logging
import uuid
import time
from typing import List, Optional

from shared.db import get_connection, return_connection

from scorer import compute_score, sort_key
from merger import (
    merge_text_entities,
    merge_numeric_ranges,
    normalize_text,
    build_resolution_entry,
)

logger = logging.getLogger(__name__)


class KnowledgeUpserter:
    """Upserts extracted DTC data into the normalized knowledge graph."""

    def __init__(self):
        self.run_id = str(uuid.uuid4())
        self.resolution_log: List[dict] = []

    def process_all(self) -> dict:
        """Run the full upsert pipeline for all DTCs.

        Returns summary dict with counts.
        """
        start = time.time()
        stats = {
            "dtc_master_upserted": 0,
            "causes_upserted": 0,
            "symptoms_upserted": 0,
            "fixes_upserted": 0,
            "sensors_upserted": 0,
            "parts_upserted": 0,
            "steps_upserted": 0,
            "sources_recorded": 0,
            "entities_merged": 0,
            "entities_rejected": 0,
        }

        conn = get_connection()
        try:
            # Ensure knowledge schema exists
            self._ensure_schema(conn)

            # Step 1: Upsert dtc_master from refined.dtc_codes
            dtc_map = self._upsert_dtc_master(conn)
            stats["dtc_master_upserted"] = len(dtc_map)

            # Step 2: For each DTC, process child entities
            for refined_dtc_id, master_id in dtc_map.items():
                s = self._process_dtc_children(conn, refined_dtc_id, master_id)
                for k, v in s.items():
                    stats[k] = stats.get(k, 0) + v

            # Step 3: Write resolution log
            self._write_resolution_log(conn)

            conn.commit()
            stats["duration_ms"] = int((time.time() - start) * 1000)
            stats["run_id"] = self.run_id
            return stats

        except Exception:
            conn.rollback()
            raise
        finally:
            return_connection(conn)

    def _ensure_schema(self, conn):
        """Create knowledge schema if it doesn't exist yet."""
        cur = conn.cursor()
        cur.execute("CREATE SCHEMA IF NOT EXISTS knowledge")

    def _upsert_dtc_master(self, conn) -> dict:
        """Upsert refined.dtc_codes -> knowledge.dtc_master.

        Returns mapping of refined_dtc_id -> knowledge_master_id.
        """
        cur = conn.cursor()

        # Check if knowledge.dtc_master exists
        cur.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'knowledge' AND table_name = 'dtc_master'
            )
        """)
        if not cur.fetchone()[0]:
            logger.warning("knowledge.dtc_master table does not exist, skipping")
            return {}

        cur.execute("""
            SELECT d.id, d.code, d.description, d.category, d.severity,
                   d.confidence_score, d.source_count
            FROM refined.dtc_codes d
            ORDER BY d.code
        """)
        rows = cur.fetchall()

        dtc_map = {}
        for row in rows:
            refined_id, code, description, category, severity, conf, src_count = row
            code = (code or "").strip().upper()
            if not code:
                continue

            # Map category to system_category
            system_category = self._map_category(category)
            severity_level = self._map_severity(severity)

            # Determine emissions_related from code prefix
            emissions_related = code.startswith("P0") and len(code) == 5

            cur.execute("""
                INSERT INTO knowledge.dtc_master
                    (code, system_category, generic_description,
                     severity_level, emissions_related, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
                ON CONFLICT (code) DO UPDATE SET
                    generic_description = COALESCE(
                        NULLIF(EXCLUDED.generic_description, ''),
                        knowledge.dtc_master.generic_description
                    ),
                    system_category = COALESCE(
                        NULLIF(EXCLUDED.system_category, ''),
                        knowledge.dtc_master.system_category
                    ),
                    severity_level = COALESCE(
                        EXCLUDED.severity_level,
                        knowledge.dtc_master.severity_level
                    ),
                    updated_at = NOW()
                RETURNING id
            """, (code, system_category, description,
                  severity_level, emissions_related))

            master_id = cur.fetchone()[0]
            dtc_map[str(refined_id)] = str(master_id)

            self.resolution_log.append(build_resolution_entry(
                "created" if src_count == 1 else "updated",
                "knowledge.dtc_master", str(master_id),
                {"code": code, "source_count": src_count,
                 "confidence": conf},
            ))

        return dtc_map

    def _process_dtc_children(self, conn, refined_dtc_id: str,
                              master_id: str) -> dict:
        """Process all child entities for a single DTC."""
        stats = {
            "causes_upserted": 0,
            "steps_upserted": 0,
            "sensors_upserted": 0,
            "sources_recorded": 0,
            "entities_merged": 0,
            "entities_rejected": 0,
        }

        cur = conn.cursor()

        # Get DTC code for sensor lookup
        cur.execute("SELECT code FROM refined.dtc_codes WHERE id = %s",
                    (refined_dtc_id,))
        row = cur.fetchone()
        if not row:
            return stats
        dtc_code = row[0]

        # Process causes
        s = self._upsert_causes(conn, refined_dtc_id, master_id)
        stats["causes_upserted"] += s.get("upserted", 0)
        stats["entities_merged"] += s.get("merged", 0)
        stats["entities_rejected"] += s.get("rejected", 0)
        stats["sources_recorded"] += s.get("sources", 0)

        # Process diagnostic steps
        s = self._upsert_diagnostic_steps(conn, refined_dtc_id, master_id)
        stats["steps_upserted"] += s.get("upserted", 0)
        stats["entities_merged"] += s.get("merged", 0)
        stats["sources_recorded"] += s.get("sources", 0)

        # Process sensors
        s = self._upsert_sensors(conn, dtc_code, master_id)
        stats["sensors_upserted"] += s.get("upserted", 0)
        stats["sources_recorded"] += s.get("sources", 0)

        return stats

    def _upsert_causes(self, conn, refined_dtc_id: str,
                       master_id: str) -> dict:
        """Upsert refined.causes -> knowledge.dtc_possible_causes."""
        cur = conn.cursor()
        stats = {"upserted": 0, "merged": 0, "rejected": 0, "sources": 0}

        # Check table exists
        if not self._table_exists(cur, "knowledge", "dtc_possible_causes"):
            return stats

        # Fetch causes with evaluation scores
        cur.execute("""
            SELECT c.id, c.description, c.likelihood, c.confidence_score,
                   c.source_chunk_id,
                   COALESCE(ce.trust_score, 0.5) AS trust,
                   COALESCE(ce.relevance_score, 0.5) AS relevance
            FROM refined.causes c
            LEFT JOIN research.chunk_evaluations ce
                ON c.source_chunk_id = ce.chunk_id
            WHERE c.dtc_id = %s
        """, (refined_dtc_id,))
        rows = cur.fetchall()

        if not rows:
            return stats

        # Build candidate list
        candidates = []
        for row in rows:
            cid, desc, likelihood, conf, chunk_id, trust, relevance = row
            prob_weight = self._likelihood_to_weight(likelihood)
            score = compute_score(
                entity_type="cause",
                avg_trust=trust,
                avg_relevance=relevance,
                evidence_count=1,
                probability_weight=prob_weight,
            )
            candidates.append({
                "id": str(cid),
                "cause": desc or "",
                "probability_weight": prob_weight,
                "avg_trust": trust,
                "avg_relevance": relevance,
                "evidence_count": 1,
                "score": score,
                "source_chunk_ids": [str(chunk_id)] if chunk_id else [],
            })

        # Merge duplicates
        merged, rejected = merge_text_entities(candidates, "cause")
        stats["merged"] = len(rejected)
        stats["rejected"] = len(rejected)

        # Rescore merged entities
        for entity in merged:
            entity["score"] = compute_score(
                entity_type="cause",
                avg_trust=entity.get("avg_trust", 0),
                avg_relevance=entity.get("avg_relevance", 0),
                evidence_count=entity.get("evidence_count", 0),
                probability_weight=entity.get("probability_weight", 0.5),
            )

        # Sort and upsert
        merged.sort(key=sort_key)
        for entity in merged:
            cur.execute("""
                INSERT INTO knowledge.dtc_possible_causes
                    (dtc_master_id, cause, probability_weight,
                     evidence_count, avg_trust, avg_relevance)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (dtc_master_id, lower(cause)) DO UPDATE SET
                    probability_weight = GREATEST(
                        knowledge.dtc_possible_causes.probability_weight,
                        EXCLUDED.probability_weight
                    ),
                    evidence_count = knowledge.dtc_possible_causes.evidence_count
                        + EXCLUDED.evidence_count,
                    avg_trust = (knowledge.dtc_possible_causes.avg_trust
                        + EXCLUDED.avg_trust) / 2.0,
                    avg_relevance = (knowledge.dtc_possible_causes.avg_relevance
                        + EXCLUDED.avg_relevance) / 2.0
                RETURNING id
            """, (master_id, entity["cause"],
                  entity.get("probability_weight", 0.5),
                  entity.get("evidence_count", 1),
                  entity.get("avg_trust", 0.5),
                  entity.get("avg_relevance", 0.5)))

            entity_id = str(cur.fetchone()[0])
            stats["upserted"] += 1

            # Record provenance
            for chunk_id in entity.get("source_chunk_ids", []):
                self._record_source(cur, "knowledge.dtc_possible_causes",
                                    entity_id, chunk_id,
                                    entity.get("avg_trust", 0),
                                    entity.get("avg_relevance", 0))
                stats["sources"] += 1

        # Log rejected
        for rej in rejected:
            self.resolution_log.append(build_resolution_entry(
                "rejected", "knowledge.dtc_possible_causes",
                rej.get("id"),
                {"reason": "duplicate_merged",
                 "merged_into": rej.get("_merged_into"),
                 "original_text": rej.get("cause", "")[:200]},
            ))

        return stats

    def _upsert_diagnostic_steps(self, conn, refined_dtc_id: str,
                                 master_id: str) -> dict:
        """Upsert refined.diagnostic_steps -> knowledge.dtc_diagnostic_steps."""
        cur = conn.cursor()
        stats = {"upserted": 0, "merged": 0, "sources": 0}

        if not self._table_exists(cur, "knowledge", "dtc_diagnostic_steps"):
            return stats

        cur.execute("""
            SELECT ds.id, ds.step_order, ds.description, ds.tools_required,
                   ds.expected_values, ds.confidence_score, ds.source_chunk_id,
                   COALESCE(ce.trust_score, 0.5) AS trust,
                   COALESCE(ce.relevance_score, 0.5) AS relevance
            FROM refined.diagnostic_steps ds
            LEFT JOIN research.chunk_evaluations ce
                ON ds.source_chunk_id = ce.chunk_id
            WHERE ds.dtc_id = %s
            ORDER BY ds.step_order
        """, (refined_dtc_id,))
        rows = cur.fetchall()

        if not rows:
            return stats

        for row in rows:
            (sid, step_order, desc, tools, expected,
             conf, chunk_id, trust, relevance) = row

            score = compute_score(
                entity_type="step",
                avg_trust=trust,
                avg_relevance=relevance,
                evidence_count=1,
            )

            cur.execute("""
                INSERT INTO knowledge.dtc_diagnostic_steps
                    (dtc_master_id, step_order, instruction,
                     evidence_count, avg_trust, avg_relevance)
                VALUES (%s, %s, %s, 1, %s, %s)
                ON CONFLICT DO NOTHING
                RETURNING id
            """, (master_id, step_order or 1, desc or "", trust, relevance))

            result = cur.fetchone()
            if result:
                entity_id = str(result[0])
                stats["upserted"] += 1
                if chunk_id:
                    self._record_source(
                        cur, "knowledge.dtc_diagnostic_steps",
                        entity_id, str(chunk_id), trust, relevance)
                    stats["sources"] += 1

        return stats

    def _upsert_sensors(self, conn, dtc_code: str, master_id: str) -> dict:
        """Upsert refined.sensors -> knowledge.dtc_related_sensors."""
        cur = conn.cursor()
        stats = {"upserted": 0, "sources": 0}

        if not self._table_exists(cur, "knowledge", "sensors"):
            return stats
        if not self._table_exists(cur, "knowledge", "dtc_related_sensors"):
            return stats

        cur.execute("""
            SELECT s.id, s.name, s.sensor_type, s.typical_range, s.unit,
                   s.source_chunk_id, s.confidence_score,
                   COALESCE(ce.trust_score, 0.5) AS trust,
                   COALESCE(ce.relevance_score, 0.5) AS relevance
            FROM refined.sensors s
            LEFT JOIN research.chunk_evaluations ce
                ON s.source_chunk_id = ce.chunk_id
            WHERE %s = ANY(s.related_dtc_codes)
        """, (dtc_code,))
        rows = cur.fetchall()

        if not rows:
            return stats

        for row in rows:
            (sid, name, stype, range_str, unit,
             chunk_id, conf, trust, relevance) = row

            # Ensure sensor_type exists
            sensor_type_id = None
            if stype:
                cur.execute("""
                    INSERT INTO knowledge.sensor_types (name)
                    VALUES (%s)
                    ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
                    RETURNING id
                """, (stype,))
                sensor_type_id = str(cur.fetchone()[0])

            # Upsert sensor
            cur.execute("""
                INSERT INTO knowledge.sensors
                    (name, sensor_type_id, manufacturer)
                VALUES (%s, %s, NULL)
                ON CONFLICT (name, COALESCE(manufacturer, ''))
                DO UPDATE SET name = EXCLUDED.name
                RETURNING id
            """, (name or "unknown", sensor_type_id))
            knowledge_sensor_id = str(cur.fetchone()[0])

            # Link to DTC
            score = compute_score(
                entity_type="sensor",
                avg_trust=trust,
                avg_relevance=relevance,
                evidence_count=1,
            )

            cur.execute("""
                INSERT INTO knowledge.dtc_related_sensors
                    (dtc_master_id, sensor_id, priority_rank,
                     evidence_count, avg_trust, avg_relevance)
                VALUES (%s, %s, %s, 1, %s, %s)
                ON CONFLICT (dtc_master_id, sensor_id) DO UPDATE SET
                    evidence_count = knowledge.dtc_related_sensors.evidence_count + 1,
                    avg_trust = (knowledge.dtc_related_sensors.avg_trust
                        + EXCLUDED.avg_trust) / 2.0,
                    avg_relevance = (knowledge.dtc_related_sensors.avg_relevance
                        + EXCLUDED.avg_relevance) / 2.0
                RETURNING id
            """, (master_id, knowledge_sensor_id,
                  stats["upserted"] + 1, trust, relevance))

            result = cur.fetchone()
            if result:
                stats["upserted"] += 1
                if chunk_id:
                    self._record_source(
                        cur, "knowledge.dtc_related_sensors",
                        str(result[0]), str(chunk_id), trust, relevance)
                    stats["sources"] += 1

        return stats

    def _record_source(self, cur, entity_table: str, entity_id: str,
                       chunk_id: str, trust: float, relevance: float):
        """Record provenance in knowledge.dtc_entity_sources."""
        if not self._table_exists(cur, "knowledge", "dtc_entity_sources"):
            return
        try:
            cur.execute("""
                INSERT INTO knowledge.dtc_entity_sources
                    (entity_table, entity_id, chunk_id,
                     trust_score, relevance_score)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
            """, (entity_table, entity_id, chunk_id, trust, relevance))
        except Exception as e:
            logger.warning(f"Failed to record source: {e}")

    def _write_resolution_log(self, conn):
        """Write all resolution log entries to knowledge.resolution_log."""
        cur = conn.cursor()
        if not self._table_exists(cur, "knowledge", "resolution_log"):
            return

        for entry in self.resolution_log:
            try:
                import json
                cur.execute("""
                    INSERT INTO knowledge.resolution_log
                        (dtc_master_id, run_id, action,
                         entity_table, entity_id, details)
                    VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                """, (
                    entry.get("dtc_master_id"),
                    self.run_id,
                    entry["action"],
                    entry.get("entity_table"),
                    entry.get("entity_id"),
                    json.dumps(entry.get("details", {})),
                ))
            except Exception as e:
                logger.warning(f"Failed to write resolution log: {e}")

    @staticmethod
    def _table_exists(cur, schema: str, table: str) -> bool:
        """Check if a table exists in the database."""
        cur.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = %s AND table_name = %s
            )
        """, (schema, table))
        return cur.fetchone()[0]

    @staticmethod
    def _map_category(category: Optional[str]) -> str:
        """Map refined category to system_category."""
        if not category:
            return "unknown"
        cat = category.lower().strip()
        mapping = {
            "powertrain": "powertrain",
            "chassis": "chassis",
            "body": "body",
            "network": "network",
            "engine": "powertrain",
            "transmission": "powertrain",
            "electrical": "electrical",
            "emissions": "emissions",
        }
        return mapping.get(cat, cat)

    @staticmethod
    def _map_severity(severity: Optional[str]) -> int:
        """Map severity text to 1-5 integer."""
        if not severity:
            return 3
        sev = severity.lower().strip()
        mapping = {
            "critical": 5, "high": 4, "medium": 3,
            "low": 2, "informational": 1, "info": 1,
        }
        return mapping.get(sev, 3)

    @staticmethod
    def _likelihood_to_weight(likelihood: Optional[str]) -> float:
        """Map likelihood text to probability_weight 0-1."""
        if not likelihood:
            return 0.5
        lik = likelihood.lower().strip()
        mapping = {
            "high": 0.85, "medium": 0.55, "low": 0.25,
            "very high": 0.95, "very low": 0.10,
            "certain": 1.0, "unlikely": 0.15,
        }
        return mapping.get(lik, 0.5)
