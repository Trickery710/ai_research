"""Vehicle Linker.

Matches extracted vehicle mentions from refined.vehicle_mentions against
the vehicle.vehicles catalog and populates relationship tables:
- vehicle.vehicle_dtc_codes
- vehicle.vehicle_engines
- vehicle.vehicle_transmissions

Also rolls up per-chunk document_categories into a majority-vote
document_type on research.documents.
"""

import sys
import logging

sys.path.insert(0, "/app")

from shared.db import get_connection, return_connection

logger = logging.getLogger(__name__)


def link_vehicles_for_document(doc_id: str) -> dict:
    """Process all unlinked vehicle mentions for chunks belonging to doc_id.

    Returns stats dict with counts of actions taken.
    """
    stats = {
        "mentions_processed": 0,
        "vehicles_matched": 0,
        "vehicles_created": 0,
        "dtc_links_created": 0,
        "doc_category_set": False,
    }

    conn = get_connection()
    try:
        cur = conn.cursor()

        # --- 1. Get unlinked vehicle mentions for this document's chunks ---
        cur.execute(
            """SELECT vm.id, vm.make, vm.model, vm.year_start, vm.year_end,
                      vm.engine, vm.transmission, vm.related_dtc_codes,
                      vm.source_chunk_id
               FROM refined.vehicle_mentions vm
               JOIN research.document_chunks dc ON vm.source_chunk_id = dc.id
               WHERE dc.document_id = %s AND vm.linked = FALSE""",
            (doc_id,)
        )
        mentions = cur.fetchall()
        stats["mentions_processed"] = len(mentions)

        for row in mentions:
            (mention_id, make, model, year_start, year_end,
             engine, transmission, dtc_codes, chunk_id) = row

            make_norm = make.strip().title()
            model_norm = model.strip()

            # Generate year range to link
            if year_start and year_end:
                years = range(year_start, year_end + 1)
            elif year_start:
                years = [year_start]
            elif year_end:
                years = [year_end]
            else:
                years = [None]

            for year in years:
                vehicle_id = _find_or_create_vehicle(
                    cur, make_norm, model_norm, year, stats
                )
                if not vehicle_id:
                    continue

                # Link DTCs to this vehicle
                for dtc_code in (dtc_codes or []):
                    dtc_code = dtc_code.strip().upper()
                    if not dtc_code:
                        continue
                    _link_dtc_to_vehicle(
                        cur, vehicle_id, dtc_code, chunk_id, stats
                    )

                # Link engine if mentioned
                if engine and engine.strip():
                    _link_engine_to_vehicle(
                        cur, vehicle_id, engine.strip(), make_norm
                    )

                # Link transmission if mentioned
                if transmission and transmission.strip():
                    _link_transmission_to_vehicle(
                        cur, vehicle_id, transmission.strip()
                    )

            # Mark mention as linked
            cur.execute(
                "UPDATE refined.vehicle_mentions SET linked = TRUE WHERE id = %s",
                (mention_id,)
            )

        # --- 2. Set document category by majority vote ---
        _set_document_category(cur, doc_id, stats)

        conn.commit()

    except Exception:
        conn.rollback()
        raise
    finally:
        return_connection(conn)

    return stats


def _find_or_create_vehicle(cur, make, model, year, stats) -> str:
    """Find an existing vehicle or create one. Returns vehicle UUID."""
    if year:
        cur.execute(
            """SELECT id FROM vehicle.vehicles
               WHERE LOWER(make) = LOWER(%s)
                 AND LOWER(model) = LOWER(%s)
                 AND year = %s
               LIMIT 1""",
            (make, model, year)
        )
    else:
        # No year - match any year for this make/model
        cur.execute(
            """SELECT id FROM vehicle.vehicles
               WHERE LOWER(make) = LOWER(%s)
                 AND LOWER(model) = LOWER(%s)
               LIMIT 1""",
            (make, model)
        )

    row = cur.fetchone()
    if row:
        stats["vehicles_matched"] += 1
        return str(row[0])

    # Create new vehicle entry
    if not year:
        return None  # Don't create vehicles without a year

    try:
        cur.execute(
            """INSERT INTO vehicle.vehicles (make, model, year)
               VALUES (%s, %s, %s)
               ON CONFLICT (year, make, model, COALESCE(generation, ''),
                           COALESCE(trim, ''))
               DO UPDATE SET updated_at = NOW()
               RETURNING id""",
            (make, model, year)
        )
        row = cur.fetchone()
        if row:
            stats["vehicles_created"] += 1
            return str(row[0])
    except Exception as e:
        logger.warning(f"Failed to create vehicle {year} {make} {model}: {e}")

    return None


def _link_dtc_to_vehicle(cur, vehicle_id, dtc_code, chunk_id, stats):
    """Link a DTC code to a vehicle via vehicle.vehicle_dtc_codes."""
    # Look up the DTC id
    cur.execute(
        "SELECT id FROM refined.dtc_codes WHERE code = %s",
        (dtc_code,)
    )
    dtc_row = cur.fetchone()
    if not dtc_row:
        return

    dtc_id = str(dtc_row[0])

    try:
        cur.execute(
            """INSERT INTO vehicle.vehicle_dtc_codes
               (vehicle_id, dtc_id, source_chunk_id, confidence_score)
               VALUES (%s, %s, %s, 0.5)
               ON CONFLICT (vehicle_id, dtc_id) DO NOTHING""",
            (vehicle_id, dtc_id, chunk_id)
        )
        if cur.rowcount > 0:
            stats["dtc_links_created"] += 1
    except Exception as e:
        logger.debug(f"DTC link failed {vehicle_id}->{dtc_code}: {e}")


def _link_engine_to_vehicle(cur, vehicle_id, engine_desc, make):
    """Find or create an engine and link to vehicle."""
    # Try to find existing engine by code
    cur.execute(
        """SELECT id FROM vehicle.engines
           WHERE LOWER(engine_code) = LOWER(%s)
           LIMIT 1""",
        (engine_desc,)
    )
    row = cur.fetchone()

    if not row:
        # Create a new engine entry
        try:
            cur.execute(
                """INSERT INTO vehicle.engines (engine_code, manufacturer)
                   VALUES (%s, %s)
                   ON CONFLICT (engine_code) DO UPDATE
                   SET updated_at = NOW()
                   RETURNING id""",
                (engine_desc, make)
            )
            row = cur.fetchone()
        except Exception as e:
            logger.debug(f"Engine create failed: {e}")
            return

    if not row:
        return

    engine_id = str(row[0])
    try:
        cur.execute(
            """INSERT INTO vehicle.vehicle_engines (vehicle_id, engine_id)
               VALUES (%s, %s)
               ON CONFLICT (vehicle_id, engine_id) DO NOTHING""",
            (vehicle_id, engine_id)
        )
    except Exception as e:
        logger.debug(f"Engine link failed: {e}")


def _link_transmission_to_vehicle(cur, vehicle_id, trans_desc):
    """Find or create a transmission and link to vehicle."""
    cur.execute(
        """SELECT id FROM vehicle.transmissions
           WHERE LOWER(transmission_code) = LOWER(%s)
           LIMIT 1""",
        (trans_desc,)
    )
    row = cur.fetchone()

    if not row:
        # Infer type from description
        desc_lower = trans_desc.lower()
        if "manual" in desc_lower:
            trans_type = "manual"
        elif any(w in desc_lower for w in ["auto", "cvt", "dct", "dsg"]):
            trans_type = "automatic"
        else:
            trans_type = "unknown"

        try:
            cur.execute(
                """INSERT INTO vehicle.transmissions
                   (transmission_code, transmission_type)
                   VALUES (%s, %s)
                   ON CONFLICT (transmission_code) DO UPDATE
                   SET updated_at = NOW()
                   RETURNING id""",
                (trans_desc, trans_type)
            )
            row = cur.fetchone()
        except Exception as e:
            logger.debug(f"Transmission create failed: {e}")
            return

    if not row:
        return

    trans_id = str(row[0])
    try:
        cur.execute(
            """INSERT INTO vehicle.vehicle_transmissions
               (vehicle_id, transmission_id)
               VALUES (%s, %s)
               ON CONFLICT (vehicle_id, transmission_id) DO NOTHING""",
            (vehicle_id, trans_id)
        )
    except Exception as e:
        logger.debug(f"Transmission link failed: {e}")


def _set_document_category(cur, doc_id, stats):
    """Set document category by majority vote from chunk-level categories."""
    cur.execute(
        """SELECT dc.category, COUNT(*) as cnt
           FROM refined.document_categories dc
           JOIN research.document_chunks ch ON dc.source_chunk_id = ch.id
           WHERE ch.document_id = %s
           GROUP BY dc.category
           ORDER BY cnt DESC
           LIMIT 1""",
        (doc_id,)
    )
    row = cur.fetchone()
    if not row:
        return

    category = row[0]

    cur.execute(
        """UPDATE research.documents
           SET document_category = %s
           WHERE id = %s""",
        (category, doc_id)
    )
    stats["doc_category_set"] = True
