#!/usr/bin/env python3
"""Extract vehicle, engine, transmission, and sensor data from crawled Wikipedia
content and populate the vehicle schema tables.

Runs inside the Docker network:
  docker compose run --rm -e PYTHONUNBUFFERED=1 researcher python /scripts/extract_vehicles.py
"""
import json
import os
import sys
import time
import psycopg2
import psycopg2.extras
import requests

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://refinery:refinery@postgres:5432/refinery"
)
OLLAMA_URL = os.environ.get("OLLAMA_BASE_URL", "http://llm-reason:11434")
MODEL = os.environ.get("REASONING_MODEL", "llama3")

VEHICLE_PROMPT = """You are an automotive data extractor. Given a text chunk from Wikipedia,
extract structured vehicle data. Respond with ONLY a JSON object.

{
  "vehicles": [
    {
      "year_start": 2018,
      "year_end": 2024,
      "make": "Toyota",
      "model": "Camry",
      "generation": "XV70",
      "trims": ["LE", "SE", "XSE", "TRD"],
      "body_style": "sedan",
      "drive_type": "FWD"
    }
  ],
  "engines": [
    {
      "engine_code": "2GR-FKS",
      "displacement_liters": 3.5,
      "fuel_type": "gasoline",
      "cylinders": 6,
      "configuration": "V",
      "aspiration": "natural",
      "horsepower": 301,
      "torque_ft_lbs": 267,
      "manufacturer": "Toyota",
      "used_in": ["Toyota Camry", "Toyota Highlander"]
    }
  ],
  "transmissions": [
    {
      "transmission_code": "A8-Direct Shift",
      "transmission_type": "automatic",
      "speeds": 8,
      "manufacturer": "Aisin"
    }
  ],
  "sensors": [
    {
      "name": "Oxygen Sensor",
      "sensor_type": "lambda",
      "typical_range": "0.1-0.9V",
      "unit": "V",
      "manufacturers": ["Bosch", "Denso", "NTK"]
    }
  ],
  "sensor_manufacturers": [
    {
      "name": "Denso",
      "country": "Japan",
      "website": "https://www.denso.com"
    }
  ]
}

Rules:
- Only extract data EXPLICITLY stated in the text.
- Use empty arrays for categories with no matches.
- year_start/year_end: production years for that generation.
- engine_code must be specific (e.g. "2GR-FE", not "V6").
- Only include data you are confident about from the text."""


def llm_generate(prompt, system_prompt, retries=2):
    """Call Ollama generate endpoint."""
    for attempt in range(retries):
        try:
            resp = requests.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": MODEL,
                    "prompt": prompt,
                    "system": system_prompt,
                    "stream": False,
                    "options": {"temperature": 0.1, "num_predict": 4096},
                    "format": "json",
                },
                timeout=120,
            )
            resp.raise_for_status()
            return resp.json().get("response", "")
        except Exception as e:
            print(f"  LLM error (attempt {attempt + 1}): {e}")
            time.sleep(2)
    return ""


def parse_json(text):
    """Parse JSON from LLM response with fallbacks."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Try extracting from markdown
    if "```json" in text:
        try:
            start = text.index("```json") + 7
            end = text.index("```", start)
            return json.loads(text[start:end].strip())
        except (json.JSONDecodeError, ValueError):
            pass
    # Try finding first { to last }
    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last > first:
        try:
            return json.loads(text[first : last + 1])
        except json.JSONDecodeError:
            pass
    return {}


def get_chunks_for_extraction(conn):
    """Get document chunks from Wikipedia crawls that likely contain vehicle data."""
    cur = conn.cursor()
    cur.execute("""
        SELECT dc.id, dc.content, d.source_url, d.title
        FROM research.document_chunks dc
        JOIN research.documents d ON dc.document_id = d.id
        WHERE d.source_url LIKE '%%wikipedia.org%%'
          AND LENGTH(dc.content) > 200
        ORDER BY d.title, dc.chunk_index
    """)
    return cur.fetchall()


def insert_vehicles(conn, vehicles):
    """Insert vehicles into vehicle.vehicles, return count."""
    cur = conn.cursor()
    inserted = 0
    for v in vehicles:
        year_start = v.get("year_start")
        year_end = v.get("year_end")
        if not year_start or not v.get("make") or not v.get("model"):
            continue

        years = range(year_start, (year_end or year_start) + 1)
        trims = v.get("trims") or [None]

        for year in years:
            for trim in trims:
                try:
                    cur.execute("""
                        INSERT INTO vehicle.vehicles
                            (year, make, model, generation, trim, body_style, drive_type)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT DO NOTHING
                    """, (
                        year, v["make"], v["model"],
                        v.get("generation"), trim,
                        v.get("body_style"), v.get("drive_type")
                    ))
                    if cur.rowcount > 0:
                        inserted += 1
                except Exception as e:
                    conn.rollback()
                    continue
    conn.commit()
    return inserted


def insert_engines(conn, engines):
    """Insert engines into vehicle.engines, return count."""
    cur = conn.cursor()
    inserted = 0
    for eng in engines:
        code = str(eng.get("engine_code") or "").strip()
        if not code:
            continue
        try:
            cur.execute("""
                INSERT INTO vehicle.engines
                    (engine_code, displacement_liters, fuel_type, cylinders,
                     configuration, aspiration, horsepower, torque_ft_lbs, manufacturer)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (engine_code) DO UPDATE SET
                    displacement_liters = COALESCE(NULLIF(EXCLUDED.displacement_liters, 0),
                                                   vehicle.engines.displacement_liters),
                    horsepower = COALESCE(EXCLUDED.horsepower, vehicle.engines.horsepower),
                    torque_ft_lbs = COALESCE(EXCLUDED.torque_ft_lbs, vehicle.engines.torque_ft_lbs),
                    updated_at = NOW()
            """, (
                code,
                eng.get("displacement_liters"),
                eng.get("fuel_type"),
                eng.get("cylinders"),
                eng.get("configuration"),
                eng.get("aspiration", "natural"),
                eng.get("horsepower"),
                eng.get("torque_ft_lbs"),
                eng.get("manufacturer"),
            ))
            if cur.rowcount > 0:
                inserted += 1
        except Exception as e:
            conn.rollback()
            continue
    conn.commit()
    return inserted


def insert_transmissions(conn, transmissions):
    """Insert transmissions into vehicle.transmissions, return count."""
    cur = conn.cursor()
    inserted = 0
    for t in transmissions:
        code = str(t.get("transmission_code") or "").strip()
        ttype = str(t.get("transmission_type") or "").strip()
        if not code or not ttype:
            continue
        try:
            cur.execute("""
                INSERT INTO vehicle.transmissions
                    (transmission_code, transmission_type, speeds, manufacturer)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (transmission_code) DO UPDATE SET
                    speeds = COALESCE(EXCLUDED.speeds, vehicle.transmissions.speeds),
                    updated_at = NOW()
            """, (code, ttype, t.get("speeds"), t.get("manufacturer")))
            if cur.rowcount > 0:
                inserted += 1
        except Exception as e:
            conn.rollback()
            continue
    conn.commit()
    return inserted


def insert_sensor_manufacturers(conn, manufacturers):
    """Insert sensor manufacturers, return count."""
    cur = conn.cursor()
    inserted = 0
    for m in manufacturers:
        name = str(m.get("name") or "").strip()
        if not name:
            continue
        try:
            cur.execute("""
                INSERT INTO vehicle.sensor_manufacturers (name, country, website)
                VALUES (%s, %s, %s)
                ON CONFLICT (name) DO NOTHING
            """, (name, m.get("country"), m.get("website")))
            if cur.rowcount > 0:
                inserted += 1
        except Exception as e:
            conn.rollback()
            continue
    conn.commit()
    return inserted


def main():
    print(f"[vehicle-extract] Connecting to database...")
    conn = psycopg2.connect(DATABASE_URL)

    print(f"[vehicle-extract] Fetching Wikipedia chunks...")
    chunks = get_chunks_for_extraction(conn)
    print(f"[vehicle-extract] Found {len(chunks)} chunks to process")

    if not chunks:
        print("[vehicle-extract] No Wikipedia chunks found. Wait for crawl pipeline to finish.")
        return

    # Process in batches by document (group chunks by title)
    docs = {}
    for chunk_id, content, url, title in chunks:
        if title not in docs:
            docs[title] = {"url": url, "chunks": []}
        docs[title]["chunks"].append(content)

    totals = {"vehicles": 0, "engines": 0, "transmissions": 0, "manufacturers": 0}

    for title, doc in docs.items():
        # Concatenate chunks (limit to ~6000 chars to fit context window)
        combined = "\n\n".join(doc["chunks"])
        if len(combined) > 6000:
            combined = combined[:6000]

        print(f"\n[vehicle-extract] Processing: {title} ({len(combined)} chars)")

        prompt = f"Extract all automotive data from this Wikipedia article:\n\n---\n{combined}\n---"
        response = llm_generate(prompt, VEHICLE_PROMPT)

        if not response:
            print(f"  No LLM response, skipping")
            continue

        data = parse_json(response)
        if not data:
            print(f"  Failed to parse JSON, skipping")
            continue

        v_count = insert_vehicles(conn, data.get("vehicles", []))
        e_count = insert_engines(conn, data.get("engines", []))
        t_count = insert_transmissions(conn, data.get("transmissions", []))
        m_count = insert_sensor_manufacturers(conn, data.get("sensor_manufacturers", []))

        totals["vehicles"] += v_count
        totals["engines"] += e_count
        totals["transmissions"] += t_count
        totals["manufacturers"] += m_count

        print(f"  Inserted: {v_count} vehicles, {e_count} engines, "
              f"{t_count} transmissions, {m_count} manufacturers")

        time.sleep(0.5)  # Don't overwhelm the LLM

    conn.close()

    print(f"\n{'='*50}")
    print(f"[vehicle-extract] DONE")
    print(f"  Total vehicles:      {totals['vehicles']}")
    print(f"  Total engines:       {totals['engines']}")
    print(f"  Total transmissions: {totals['transmissions']}")
    print(f"  Total manufacturers: {totals['manufacturers']}")


if __name__ == "__main__":
    main()
