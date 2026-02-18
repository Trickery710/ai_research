# Agent Prompts Reference

Quick-read summary of every LLM prompt in the pipeline.
Edit prompts in `config/prompts.yaml`, then run `./scripts/manage-prompts.sh apply`.

---

## Pipeline Overview

```
URL -> [Crawler] -> [Chunker] -> [Embedder] -> [Evaluator] -> [Extractor] -> [Conflict Resolver] -> Knowledge Graph
                                                                                   |
                                                                            [Verifier] (timer)

[Monitor] -> alerts -> [Healer] -> auto-fix
[Orchestrator] -> [Researcher] -> URLs -> Crawler
                -> [Auditor] -> coverage reports
```

---

## 1. Evaluation Worker

| Field | Value |
|-------|-------|
| **File** | `workers/evaluation/worker.py` |
| **LLM** | llm-eval (gemma3:12b on RTX 3070, GPU 2) |
| **Temperature** | 0.2 |
| **Purpose** | Score each chunk's trustworthiness and diagnostic relevance |

### System Prompt (summary)

Evaluates text chunks and returns JSON with:
- `trust_score` (0.0-1.0) - source credibility
- `relevance_score` (0.0-1.0) - diagnostic utility
- `automotive_domain` - one of: obd, electrical, engine, transmission, brakes, suspension, hvac, body, general, unknown
- `reasoning` - brief explanation

### Trust Score Anchors

| Range | Meaning |
|-------|---------|
| 0.9-1.0 | OEM/factory data |
| 0.7-0.85 | Professional repair guide, well-sourced article |
| 0.4-0.65 | Forum post with specifics, community-verified |
| 0.2-0.35 | Anecdotal or vague claims |
| 0.0-0.15 | Spam, ads, unverifiable |

### Relevance Score Anchors

| Range | Meaning |
|-------|---------|
| 0.9-1.0 | Step-by-step diagnostic with measurements |
| 0.7-0.85 | DTC explanation with causes/symptoms |
| 0.5-0.65 | General automotive knowledge for diagnostics |
| 0.25-0.4 | Tangentially related automotive content |
| 0.0-0.2 | Not automotive or not useful |

### Gate

Chunks with `relevance_score < 0.3` are **excluded** from extraction.

---

## 2. Extraction Worker

| Field | Value |
|-------|-------|
| **File** | `workers/extraction/worker.py` |
| **LLM** | llm-reason (gemma3:12b on RTX 3080, GPU 1) |
| **Temperature** | 0.1 |
| **Purpose** | Extract structured automotive data from relevant chunks |

### System Prompt (summary)

Extracts JSON with these fields:
- `dtc_codes[]` - code, description, category, severity
- `causes[]` - dtc_code, description, likelihood
- `diagnostic_steps[]` - dtc_code, step_order, description, tools_required, expected_values
- `sensors[]` - name, sensor_type, typical_range, unit, related_dtc_codes
- `tsb_references[]` - tsb_number, title, affected_models, related_dtc_codes, summary
- `vehicles_mentioned[]` - make, model, year_start, year_end, engine, transmission, related_dtc_codes
- `document_category` - single classification

### Key Rules

- Only extract data **explicitly stated** in text (no fabrication)
- DTC pattern: `[PBCU][0-9A-Fa-f]{4}` (e.g., P0171, B0001, U0100)
- Categories: powertrain, chassis, body, network
- Severity: critical, moderate, minor, informational
- Likelihood: high, medium, low
- Document categories: repair_procedure, diagnostic_guide, dtc_reference, tsb_bulletin, wiring_diagram, parts_catalog, forum_discussion, owners_manual, recall_notice, general_reference

---

## 3. Verification Worker

| Field | Value |
|-------|-------|
| **File** | `workers/verify/worker.py` |
| **LLM** | OpenAI gpt-4o-mini (external API) |
| **Purpose** | Cross-verify extracted DTC data for accuracy |

### System Prompt (summary)

Verifies DTC information and returns:
- `overall_accuracy` (0.0-1.0)
- Per-field results: confirmed, corrected, disputed, uncertain
- `confidence_adjustment` (-0.3 to +0.3) - applied to the DTC's confidence score

### Trigger

Runs on a timer (every 30s), processes batches of 5 DTCs.

---

## 4. Healing Analyzer

| Field | Value |
|-------|-------|
| **File** | `workers/healing/analyzer.py` |
| **LLM** | llm-reason (gemma3:12b on RTX 3080, GPU 1) |
| **Temperature** | 0.2 |
| **Purpose** | Analyze system alerts and propose safe auto-fix actions |

### System Prompt (summary)

Analyzes alerts and returns:
- `action` - what to do
- `confidence` (0.0-1.0) - how sure
- `reasoning` - why
- `alternative_actions` - fallbacks

### Available Actions

| Action | Auto-Allowed | Description |
|--------|-------------|-------------|
| `restart_worker:<name>` | Yes | Restart a specific worker |
| `requeue_documents:<stage>` | Yes | Re-queue stuck docs |
| `requeue_errors` | Yes | Reset error docs, re-queue |
| `clear_stale_locks` | Yes | Delete Redis locks > 1hr |
| `restart_container:<name>` | **No** | Too broad, needs human |
| `database_operations` | **No** | All DB mods forbidden |
| `delete_data` | **No** | All deletion forbidden |
| `escalate_to_human` | N/A | Flag for manual review |

### Safety Gates

- Confidence must be >= **0.7** to auto-execute
- Max **10 actions/hour**
- **120s cooldown** between actions
- Same alert not processed twice

---

## 5. Research Gap Analyzer

| Field | Value |
|-------|-------|
| **File** | `workers/researcher/gap_analyzer.py` |
| **LLM** | llm-reason (gemma3:12b on RTX 3080, GPU 1) |
| **Purpose** | Identify what the knowledge base is missing and generate search queries |

### Prompt (summary)

Given a database snapshot, generates 3-8 search queries targeting:
- DTCs with low confidence or few sources
- DTCs missing causes or diagnostic steps
- Thin coverage prefixes
- Practical mechanic needs (symptoms, causes, sensor readings)

---

## 6. Research Query Generator

| Field | Value |
|-------|-------|
| **File** | `workers/researcher/query_generator.py` |
| **LLM** | llm-reason (gemma3:12b on RTX 3080, GPU 1) |
| **Purpose** | Generate specific URLs for DTC codes from trusted domains |

### Trusted Domains

obd-codes.com, engine-codes.com, dtcbase.com, repairpal.com, yourmechanic.com, fixdapp.com, autozone.com, aa1car.com, troublecodes.net

### Deterministic URL Templates (Tier 1, no LLM)

```
https://www.obd-codes.com/{code_lower}
https://www.engine-codes.com/{code_lower}
https://dtcbase.com/{code_upper}
https://www.autozone.com/diy/check-engine-light/{code_lower}
```

---

## Non-LLM Agents (No Prompts)

| Agent | File | Method |
|-------|------|--------|
| Crawler | `workers/crawler/worker.py` | HTTP fetch + text extraction |
| Chunker | `workers/chunking/worker.py` | 500-char overlapping splits |
| Embedder | `workers/embedding/worker.py` | nomic-embed-text (768-dim vectors) |
| Conflict Resolver | `workers/conflict/worker.py` | Deterministic scoring + dedup |
| Monitor | `workers/monitoring/worker.py` | Threshold-based anomaly detection |
| Orchestrator | `workers/orchestrator/worker.py` | Deterministic OODA loop |
| Auditor | `workers/auditor/` | SQL queries + coverage math |
