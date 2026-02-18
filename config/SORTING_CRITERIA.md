# Sorting & Scoring Criteria Reference

How data flows through the pipeline and how items are ranked, scored, and filtered at each stage.

---

## Pipeline Flow & Gates

```
Crawl -> Chunk -> Embed -> Evaluate -> Extract -> Resolve -> Knowledge Graph
                              |
                          GATE: relevance >= 0.3
                          (chunks below this are skipped)
```

---

## 1. Evaluation Scoring (Chunk Level)

**Where:** `workers/evaluation/worker.py`
**LLM:** gemma3:12b on RTX 3070

Each chunk gets two scores from the LLM:

### Trust Score (0.0 - 1.0)

Measures source credibility.

```
~0.9-1.0  OEM/factory data
~0.7-0.85 Professional repair guide
~0.4-0.65 Forum post with specific details
~0.2-0.35 Anecdotal or vague claims
~0.0-0.15 Spam/ads/unverifiable
```

Factors: specificity of claims, part numbers, technical depth, consistency with automotive principles.

### Relevance Score (0.0 - 1.0)

Measures diagnostic utility.

```
~0.9-1.0  Step-by-step diagnostic with measurements
~0.7-0.85 DTC explanation with causes/symptoms
~0.5-0.65 General automotive knowledge
~0.25-0.4 Tangentially related
~0.0-0.2  Not automotive / not useful
```

Factors: actionability, DTC codes present, completeness.

### Relevance Gate

**Chunks with relevance_score < 0.3 are excluded from extraction.**

---

## 2. Conflict Resolution Scoring (Entity Level)

**Where:** `workers/conflict/scorer.py`
**Method:** Deterministic formula (no LLM)

### Unified Score Formula

```
S = EQS + CS + VSS + PIS

Where S is in range [0, 100]
```

### Component Breakdown

#### Evidence Quality Score (0 - 50 points)

```
quality = 0.65 * avg_trust_score + 0.35 * avg_relevance_score
EQS = 50 * quality
```

Trust matters more than relevance (65/35 split).

#### Consensus Score (0 - 20 points)

```
consensus = clamp(ln(1 + evidence_count) / ln(1 + 10), 0, 1)
CS = 20 * consensus
```

| Evidence Count | Score |
|---------------|-------|
| 1 source | ~6 |
| 3 sources | ~12 |
| 5 sources | ~15 |
| 10 sources | 20 (max) |

Logarithmic - diminishing returns after ~5 sources.

#### Vehicle Specificity Score (-20 to +20 points)

| Condition | Score |
|-----------|-------|
| Tied to exact make/model/year matching context | +20 |
| Only make matches | +12 |
| OEM-agnostic (master-level, no make) | +6 |
| Conflicts with context (wrong make/model/year) | **-20** |

Can be negative - penalizes mismatched vehicle data.

#### Practical Impact Score (0 - 10 points)

| Entity Type | Formula |
|------------|---------|
| Fixes / parts | `10 * clamp(ln(1 + confirmed_repairs) / ln(51))` |
| Causes | `10 * clamp(probability_weight)` |
| Symptoms | `10 * clamp(frequency / 10)` |
| Forum threads | 6 if solution marked, else 0 |
| Steps / sensors / live data | 0 (neutral) |

### Sort Order (when scores tie)

1. Score DESC
2. evidence_count DESC
3. avg_trust DESC
4. avg_relevance DESC
5. id ASC (stable tie-breaker)

---

## 3. Confidence Score (DTC Level)

**Where:** `workers/conflict/worker.py`
**Method:** Deterministic formula

```
confidence = min(1.0, 0.3 * source_factor + 0.7 * avg_trust)

source_factor = min(1.0, source_count / 5.0)
```

| Sources | Avg Trust | Confidence |
|---------|-----------|------------|
| 1 | 0.5 | 0.41 |
| 1 | 0.8 | 0.62 |
| 3 | 0.5 | 0.53 |
| 5 | 0.8 | 0.86 |
| 5 | 0.9 | 0.93 |

More sources AND higher trust = higher confidence.

---

## 4. Completeness Score (Audit Level)

**Where:** `workers/auditor/quality_analyzer.py`
**Method:** Weighted checklist

```
Score = sum of weights for present attributes
```

| Attribute | Weight |
|-----------|--------|
| Has diagnostic steps | 0.30 |
| Has causes | 0.25 |
| Has description | 0.15 |
| Has sensors | 0.10 |
| Has TSB references | 0.10 |
| Has category | 0.05 |
| Has severity | 0.05 |
| **Total** | **1.00** |

A DTC is "complete" when score = 1.0 (has everything).
Diagnostic steps and causes together account for 55% of completeness.

---

## 5. Monitoring Detection Thresholds

**Where:** `workers/monitoring/detectors.py`
**Method:** Threshold comparison

### Detection Rules

| Detector | Threshold | Severity | Trigger |
|----------|-----------|----------|---------|
| Stalled Queue | 300s unchanged | high (>10 items), medium | Queue depth > 0 and unchanged |
| Error Rate Spike | >15% error rate | critical (>50%), high | Min 5 samples |
| Processing Slowdown | >3x historical avg | medium | Recent avg vs historical |
| Unhealthy Container | >60s unhealthy | critical | Docker health status |
| Container Starting | >120s starting | high | Still not ready |
| Stuck Documents | >30 min same stage | medium | Document stage timestamp |
| Error Accumulation | >=10 error docs | high | Count in error state |

### Environment Variable Overrides

```bash
QUEUE_STALL_THRESHOLD=300        # seconds
ERROR_RATE_THRESHOLD=0.15        # 15%
PROCESSING_TIME_MULTIPLIER=3.0   # 3x historical
ERROR_DOCUMENT_THRESHOLD=10      # doc count
```

---

## 6. Healing Safety Gates

**Where:** `workers/healing/executor.py` + `workers/healing/safety.py`

| Gate | Threshold |
|------|-----------|
| Minimum confidence | 0.7 |
| Max actions per hour | 10 |
| Cooldown between actions | 120 seconds |
| Idempotency window | Same alert not re-processed |
| Auto-fix master switch | `AUTO_FIX_ENABLED=true` |

### Allowed vs Denied Actions

```
ALLOWED: restart_worker, requeue_documents, requeue_errors, clear_stale_locks
DENIED:  restart_container, database_operations, delete_data
```

---

## 7. Research Rate Limits

**Where:** `workers/researcher/worker.py`

| Limit | Default | Env Var |
|-------|---------|---------|
| URLs per hour | 60 | MAX_URLS_PER_HOUR |
| Per domain per hour | 5 | MAX_PER_DOMAIN_PER_HOUR |
| Cooldown between fetches | 15s | RESEARCH_COOLDOWN |
| URLs per autonomous cycle | 4 | AUTONOMOUS_URLS_PER_CYCLE |
| Autonomous cycle interval | 60s | AUTONOMOUS_INTERVAL |

---

## 8. Coverage Gap Detection

**Where:** `workers/auditor/coverage_analyzer.py`

### DTC Prefix Categories

| Prefix | Category |
|--------|----------|
| P0 | Powertrain (generic OBD-II) |
| P1 | Powertrain (manufacturer-specific) |
| P2 | Powertrain (generic extended) |
| P3 | Powertrain (reserved) |
| B0-B1 | Body (generic / manufacturer) |
| C0-C1 | Chassis (generic / manufacturer) |
| U0-U1 | Network (generic / manufacturer) |

### Gap Detection

```
Expected density: 30 codes per 100-range
Gap flagged when: count_in_range < 5 AND total_for_prefix > 10
Priority: "high" if count = 0, else "medium"
```

### Confidence Tiers

```
Low:    < 0.3
Medium: 0.3 - 0.7
High:   >= 0.7
```

---

## 9. Verification Confidence Adjustment

**Where:** `workers/verify/worker.py`

The OpenAI verification worker can adjust a DTC's confidence score:

```
confidence_adjustment: -0.3 to +0.3
```

Applied additively to the existing confidence score, clamped to [0.0, 1.0].

Field-level verdicts: confirmed, corrected, disputed, uncertain.
