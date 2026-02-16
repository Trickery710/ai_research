-- ==========================================================
-- Seed Data: P0301 (Cylinder 1 Misfire Detected)
-- ==========================================================
-- Demonstrates the full knowledge graph for one DTC code.

-- 1. Supporting reference data
INSERT INTO knowledge.makes (id, name) VALUES
    ('a0000000-0000-0000-0000-000000000001', 'Ford')
ON CONFLICT (name) DO NOTHING;

INSERT INTO knowledge.models (id, make_id, name) VALUES
    ('b0000000-0000-0000-0000-000000000001',
     'a0000000-0000-0000-0000-000000000001', 'F-150')
ON CONFLICT (make_id, name) DO NOTHING;

INSERT INTO knowledge.sensor_types (id, name, description) VALUES
    ('c0000000-0000-0000-0000-000000000001', 'oxygen', 'Exhaust oxygen sensor'),
    ('c0000000-0000-0000-0000-000000000002', 'position', 'Crankshaft/camshaft position')
ON CONFLICT (name) DO NOTHING;

INSERT INTO knowledge.sensors (id, name, sensor_type_id) VALUES
    ('d0000000-0000-0000-0000-000000000001', 'O2 Sensor Bank 1 Sensor 1',
     'c0000000-0000-0000-0000-000000000001'),
    ('d0000000-0000-0000-0000-000000000002', 'Crankshaft Position Sensor',
     'c0000000-0000-0000-0000-000000000002')
ON CONFLICT (name, COALESCE(manufacturer, '')) DO NOTHING;

INSERT INTO knowledge.parts (id, name, part_number, category) VALUES
    ('e0000000-0000-0000-0000-000000000001', 'Ignition Coil Pack', 'DG-508', 'ignition'),
    ('e0000000-0000-0000-0000-000000000002', 'Spark Plug', 'SP-493', 'ignition')
ON CONFLICT (name, COALESCE(part_number, '')) DO NOTHING;

INSERT INTO knowledge.forum_threads (id, platform, external_url, title, author) VALUES
    ('f0000000-0000-0000-0000-000000000001', 'f150forum.com',
     'https://www.f150forum.com/threads/p0301-misfire-cyl1.12345/',
     'P0301 Misfire on 5.0 Coyote - Fixed!', 'dieseldan'),
    ('f0000000-0000-0000-0000-000000000002', 'reddit.com',
     'https://www.reddit.com/r/MechanicAdvice/comments/abc123/',
     'P0301 keeps coming back after spark plug change', 'wrench_monkey')
ON CONFLICT DO NOTHING;

-- 2. DTC Master
INSERT INTO knowledge.dtc_master (
    id, code, system_category, subsystem, generic_description,
    severity_level, driveability_impact, emissions_related
) VALUES (
    '10000000-0000-0000-0000-000000000301',
    'P0301',
    'powertrain', 'ignition',
    'Cylinder 1 Misfire Detected. The PCM has detected that cylinder 1 is not contributing its expected power output.',
    4, true, true
) ON CONFLICT (code) DO UPDATE SET
    generic_description = EXCLUDED.generic_description,
    updated_at = NOW();

-- 3. OEM Variant (Ford F-150 2018-2023)
INSERT INTO knowledge.dtc_oem_variant (
    id, dtc_master_id, make_id, model_id, year_start, year_end,
    oem_description, tsb_reference, known_pattern_failure
) VALUES (
    '11000000-0000-0000-0000-000000000001',
    '10000000-0000-0000-0000-000000000301',
    'a0000000-0000-0000-0000-000000000001',
    'b0000000-0000-0000-0000-000000000001',
    2018, 2023,
    'Cylinder 1 misfire - check for carbon buildup on intake valves (direct injection). TSB 19-2346 applies.',
    'TSB 19-2346',
    true
) ON CONFLICT DO NOTHING;

-- 4. Symptoms (3)
INSERT INTO knowledge.dtc_symptoms (dtc_master_id, symptom, frequency_score, evidence_count, avg_trust, avg_relevance) VALUES
    ('10000000-0000-0000-0000-000000000301',
     'Rough idle with noticeable engine shake at stop lights', 9, 12, 0.82, 0.91),
    ('10000000-0000-0000-0000-000000000301',
     'Flashing check engine light during acceleration', 8, 8, 0.78, 0.88),
    ('10000000-0000-0000-0000-000000000301',
     'Reduced fuel economy (10-15% decrease from normal)', 6, 5, 0.65, 0.72)
ON CONFLICT (dtc_master_id, lower(symptom)) DO NOTHING;

-- 5. Possible Causes (3 with weights)
INSERT INTO knowledge.dtc_possible_causes (dtc_master_id, cause, probability_weight, evidence_count, avg_trust, avg_relevance) VALUES
    ('10000000-0000-0000-0000-000000000301',
     'Worn or fouled spark plug in cylinder 1', 0.85, 15, 0.88, 0.92),
    ('10000000-0000-0000-0000-000000000301',
     'Failed ignition coil pack on cylinder 1', 0.72, 11, 0.84, 0.89),
    ('10000000-0000-0000-0000-000000000301',
     'Vacuum leak at intake manifold gasket near cylinder 1', 0.45, 6, 0.71, 0.78)
ON CONFLICT (dtc_master_id, lower(cause)) DO NOTHING;

-- 6. Verified Fixes (2 with cost/labor)
INSERT INTO knowledge.dtc_verified_fixes (
    dtc_master_id, make_id, model_id, engine_code,
    fix_description, confirmed_repair_count,
    average_cost, average_labor_hours,
    evidence_count, avg_trust, avg_relevance
) VALUES
    ('10000000-0000-0000-0000-000000000301',
     'a0000000-0000-0000-0000-000000000001',
     'b0000000-0000-0000-0000-000000000001',
     '5.0L Coyote',
     'Replace spark plug in cylinder 1 with OEM SP-493 iridium plug. Torque to 11 ft-lbs. Gap 0.052 inches.',
     42, 35.00, 0.5, 18, 0.90, 0.94),
    ('10000000-0000-0000-0000-000000000301',
     'a0000000-0000-0000-0000-000000000001',
     'b0000000-0000-0000-0000-000000000001',
     '5.0L Coyote',
     'Replace ignition coil pack on cylinder 1. Use Motorcraft DG-508 or equivalent. Clear codes and test drive.',
     28, 65.00, 0.75, 14, 0.86, 0.91);

-- 7. Related Sensors (2)
INSERT INTO knowledge.dtc_related_sensors (
    dtc_master_id, sensor_id, priority_rank,
    evidence_count, avg_trust, avg_relevance
) VALUES
    ('10000000-0000-0000-0000-000000000301',
     'd0000000-0000-0000-0000-000000000001', 1, 8, 0.79, 0.85),
    ('10000000-0000-0000-0000-000000000301',
     'd0000000-0000-0000-0000-000000000002', 2, 5, 0.75, 0.80)
ON CONFLICT (dtc_master_id, sensor_id) DO NOTHING;

-- 8. Related Parts (2)
INSERT INTO knowledge.dtc_related_parts (
    dtc_master_id, part_category, part_id, priority_rank,
    evidence_count, avg_trust, avg_relevance
) VALUES
    ('10000000-0000-0000-0000-000000000301',
     'ignition', 'e0000000-0000-0000-0000-000000000002', 1, 15, 0.88, 0.92),
    ('10000000-0000-0000-0000-000000000301',
     'ignition', 'e0000000-0000-0000-0000-000000000001', 2, 11, 0.84, 0.89)
ON CONFLICT (dtc_master_id, part_id) DO NOTHING;

-- 9. Diagnostic Steps (5 with pass/fail decision tree)
-- Step 1: Check for spark
INSERT INTO knowledge.dtc_diagnostic_steps (
    id, dtc_master_id, step_order, instruction,
    terminal_outcome_flag, evidence_count, avg_trust, avg_relevance
) VALUES
    ('20000000-0000-0000-0000-000000000001',
     '10000000-0000-0000-0000-000000000301', 1,
     'Connect scan tool. Verify P0301 is the only active misfire code. Check freeze frame data for RPM and load conditions at time of misfire.',
     false, 10, 0.85, 0.92);

-- Step 2: Swap coil packs
INSERT INTO knowledge.dtc_diagnostic_steps (
    id, dtc_master_id, step_order, instruction,
    terminal_outcome_flag, evidence_count, avg_trust, avg_relevance
) VALUES
    ('20000000-0000-0000-0000-000000000002',
     '10000000-0000-0000-0000-000000000301', 2,
     'Swap ignition coil from cylinder 1 with cylinder 2. Clear codes and run engine for 5 minutes. If misfire moves to cylinder 2, coil is faulty.',
     false, 12, 0.88, 0.94);

-- Step 3: Check spark plug
INSERT INTO knowledge.dtc_diagnostic_steps (
    id, dtc_master_id, step_order, instruction,
    terminal_outcome_flag, evidence_count, avg_trust, avg_relevance
) VALUES
    ('20000000-0000-0000-0000-000000000003',
     '10000000-0000-0000-0000-000000000301', 3,
     'Remove and inspect spark plug from cylinder 1. Check gap (spec: 0.052"), electrode wear, carbon fouling, or oil contamination. Replace if worn or fouled.',
     false, 14, 0.90, 0.93);

-- Step 4: Compression test
INSERT INTO knowledge.dtc_diagnostic_steps (
    id, dtc_master_id, step_order, instruction,
    terminal_outcome_flag, evidence_count, avg_trust, avg_relevance
) VALUES
    ('20000000-0000-0000-0000-000000000004',
     '10000000-0000-0000-0000-000000000301', 4,
     'Perform compression test on cylinder 1. Normal: 150-180 PSI. If below 120 PSI or >15% variance from other cylinders, suspect mechanical issue (valves, rings, head gasket).',
     false, 7, 0.82, 0.88);

-- Step 5: Terminal - injector test
INSERT INTO knowledge.dtc_diagnostic_steps (
    id, dtc_master_id, step_order, instruction,
    terminal_outcome_flag, evidence_count, avg_trust, avg_relevance
) VALUES
    ('20000000-0000-0000-0000-000000000005',
     '10000000-0000-0000-0000-000000000301', 5,
     'Test fuel injector on cylinder 1. Measure resistance (spec: 11-18 ohms). Check spray pattern using noid light. If injector is faulty, replace and retest.',
     true, 5, 0.80, 0.86);

-- Set pass/fail links for decision tree
UPDATE knowledge.dtc_diagnostic_steps SET
    pass_next_step_id = '20000000-0000-0000-0000-000000000002'
WHERE id = '20000000-0000-0000-0000-000000000001';

UPDATE knowledge.dtc_diagnostic_steps SET
    pass_next_step_id = '20000000-0000-0000-0000-000000000003',
    fail_next_step_id = NULL  -- fail = coil moved the misfire, replace coil (terminal)
WHERE id = '20000000-0000-0000-0000-000000000002';

UPDATE knowledge.dtc_diagnostic_steps SET
    pass_next_step_id = '20000000-0000-0000-0000-000000000004',
    fail_next_step_id = NULL  -- fail = plug was bad, replace plug (terminal)
WHERE id = '20000000-0000-0000-0000-000000000003';

UPDATE knowledge.dtc_diagnostic_steps SET
    pass_next_step_id = '20000000-0000-0000-0000-000000000005',
    fail_next_step_id = NULL  -- fail = low compression, mechanical issue (terminal)
WHERE id = '20000000-0000-0000-0000-000000000004';

-- 10. Forum Threads (2)
INSERT INTO knowledge.dtc_forum_threads (
    dtc_master_id, thread_id, solution_marked,
    evidence_count, avg_trust, avg_relevance
) VALUES
    ('10000000-0000-0000-0000-000000000301',
     'f0000000-0000-0000-0000-000000000001', true, 3, 0.72, 0.81),
    ('10000000-0000-0000-0000-000000000301',
     'f0000000-0000-0000-0000-000000000002', false, 2, 0.55, 0.68)
ON CONFLICT (dtc_master_id, thread_id) DO NOTHING;

-- 11. Live Data Parameters (1 set)
INSERT INTO knowledge.dtc_live_data_parameters (
    dtc_master_id, pid_name, normal_range_min, normal_range_max, unit,
    evidence_count, avg_trust, avg_relevance
) VALUES
    ('10000000-0000-0000-0000-000000000301',
     'Misfire Count Cyl 1', 0, 0, 'count', 8, 0.83, 0.90),
    ('10000000-0000-0000-0000-000000000301',
     'RPM at Misfire', 600, 3000, 'rpm', 6, 0.78, 0.85),
    ('10000000-0000-0000-0000-000000000301',
     'Engine Load at Misfire', 15, 85, 'percent', 5, 0.75, 0.82)
ON CONFLICT (dtc_master_id, pid_name) DO NOTHING;

-- 12. AI Explanation
INSERT INTO knowledge.dtc_ai_explanations (
    dtc_master_id,
    explanation_simple,
    explanation_advanced,
    diagnostic_strategy,
    confidence_score,
    model_used
) VALUES (
    '10000000-0000-0000-0000-000000000301',
    'Your engine''s cylinder 1 is not firing properly. This causes rough running, poor fuel economy, and can damage your catalytic converter if not fixed. The most common fix is replacing the spark plug or ignition coil on that cylinder.',
    'P0301 indicates the PCM detected a misfire event in cylinder 1 via crankshaft position sensor acceleration analysis. The misfire counter exceeded the Type A or Type B threshold during the current drive cycle. Root causes include degraded spark plug (most common, ~85% probability), failed COP (coil-on-plug) unit (~72%), vacuum leak at the intake manifold gasket (~45%), or less commonly, fuel injector failure or mechanical issues (low compression from valve seal or piston ring wear). Direct injection engines are additionally susceptible to carbon buildup on intake valves reducing airflow to the cylinder.',
    'Start with least invasive tests: 1) Verify code and check for companion codes. 2) Swap coil packs between cylinders to isolate electrical vs mechanical. 3) Inspect spark plug for wear/fouling. 4) If spark and coil are good, perform compression test. 5) Test fuel injector last. This sequence minimizes unnecessary parts replacement and labor.',
    0.88,
    'mistral'
) ON CONFLICT (dtc_master_id) DO UPDATE SET
    explanation_simple = EXCLUDED.explanation_simple,
    explanation_advanced = EXCLUDED.explanation_advanced,
    diagnostic_strategy = EXCLUDED.diagnostic_strategy,
    confidence_score = EXCLUDED.confidence_score,
    updated_at = NOW();
