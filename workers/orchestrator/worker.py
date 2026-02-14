"""Orchestrator worker: master coordinator running a 60-second OODA loop.

Observe -> Orient -> Decide -> Act cycle that manages tasks, monitors
resources, and directs the researcher and auditor agents.
"""
import sys
import os
import time
import traceback
import json

sys.path.insert(0, "/app")

from shared.config import Config
from shared.redis_client import get_redis, pop_job, push_job
from shared.db import execute_query

CYCLE_INTERVAL = int(os.environ.get("ORCHESTRATOR_CYCLE", 60))
AUTO_RESEARCH = os.environ.get("ORCHESTRATOR_AUTO_RESEARCH", "true").lower() == "true"
COMMAND_QUEUE = "orchestrator:commands"
RESEARCH_QUEUE = "orchestrator:research"
AUDIT_QUEUE = "orchestrator:audit"

_cycle_number = 0


def observe():
    """Phase 1: Collect system state, task statuses, and latest intel."""
    from orchestrator.resource_monitor import get_system_state
    from orchestrator.task_manager import get_task_counts, get_active_tasks, get_pending_tasks
    from orchestrator.planner import get_latest_audit_report

    state = get_system_state()
    task_counts = get_task_counts()
    active_tasks = get_active_tasks()
    pending_tasks = get_pending_tasks(limit=5)
    audit_report = get_latest_audit_report()

    return {
        "system_state": state,
        "task_counts": task_counts,
        "active_task_count": len(active_tasks),
        "pending_task_count": len(pending_tasks),
        "pending_tasks": pending_tasks,
        "audit_report": audit_report,
    }


def orient(observation):
    """Phase 2: Analyze the situation and identify what needs attention."""
    state = observation["system_state"]
    audit = observation.get("audit_report")

    situation = {
        "pipeline_idle": state.get("pipeline_idle", False),
        "gpu_available": state.get("gpu_available", True),
        "crawl_available": state.get("crawl_available", True),
        "total_queued": state.get("total_queued", 0),
        "has_audit_data": audit is not None,
        "active_tasks": observation["active_task_count"],
        "pending_tasks": observation["pending_task_count"],
    }

    return situation


def decide(situation, observation):
    """Phase 3: Determine actions based on situation assessment."""
    from orchestrator.planner import decide_next_actions

    actions = decide_next_actions(
        observation["system_state"],
        observation.get("audit_report"),
    )

    # If auto-research is disabled, filter out research actions
    if not AUTO_RESEARCH:
        actions = [a for a in actions if a.get("type") != "research"]

    return actions


def act(actions, observation):
    """Phase 4: Execute decided actions."""
    from orchestrator.task_manager import (
        create_task, has_pending_task_of_type, start_task,
        TASK_RESEARCH, TASK_AUDIT,
    )

    executed = []

    for action in actions:
        action_type = action.get("type")

        if action_type == "wait":
            print(f"[orchestrator] Waiting: {action.get('reason')}")
            executed.append({"action": "wait", "reason": action.get("reason")})

        elif action_type == "idle":
            # Nothing to do
            executed.append({"action": "idle"})

        elif action_type == "trigger_audit":
            if not has_pending_task_of_type(TASK_AUDIT):
                task_id = create_task(TASK_AUDIT, priority=3, assigned_to="auditor")
                if task_id:
                    start_task(task_id)
                    push_job(AUDIT_QUEUE, json.dumps({
                        "type": "full_audit",
                        "task_id": task_id,
                    }))
                    print(f"[orchestrator] Triggered audit (task={task_id})")
                    executed.append({"action": "trigger_audit", "task_id": task_id})

        elif action_type == "research":
            subtype = action.get("subtype", "general")
            target_codes = action.get("target_codes", [])
            target_ranges = action.get("target_ranges", [])

            if not has_pending_task_of_type(TASK_RESEARCH):
                payload = {
                    "subtype": subtype,
                    "target_codes": target_codes,
                    "target_ranges": target_ranges,
                }
                task_id = create_task(
                    TASK_RESEARCH, priority=action.get("priority", 5),
                    payload=payload, assigned_to="researcher"
                )
                if task_id:
                    start_task(task_id)
                    push_job(RESEARCH_QUEUE, json.dumps({
                        "type": subtype,
                        "task_id": task_id,
                        "target_codes": target_codes,
                        "target_ranges": target_ranges,
                    }))
                    print(
                        f"[orchestrator] Dispatched research: {subtype} "
                        f"codes={target_codes[:3]} ranges={target_ranges[:3]} "
                        f"(task={task_id})"
                    )
                    executed.append({
                        "action": "research",
                        "subtype": subtype,
                        "task_id": task_id,
                    })

        elif action_type == "alert":
            print(f"[orchestrator] ALERT: {action.get('reason')}")
            executed.append({"action": "alert", "reason": action.get("reason")})

    return executed


def process_commands():
    """Check for and process any incoming commands from other agents or API."""
    from orchestrator.task_manager import complete_task

    processed = 0
    while processed < 10:  # Max 10 commands per cycle
        cmd_json = pop_job(COMMAND_QUEUE, timeout=0)
        if not cmd_json:
            break

        try:
            cmd = json.loads(cmd_json)
            source = cmd.get("source", "unknown")
            cmd_type = cmd.get("type", "unknown")
            print(f"[orchestrator] Command from {source}: {cmd_type}")

            if cmd_type == "audit_findings":
                # Audit findings trigger research
                findings = cmd.get("findings", [])
                print(f"[orchestrator] Received {len(findings)} audit findings")

            elif cmd_type == "research_complete":
                task_id = cmd.get("task_id")
                if task_id:
                    complete_task(task_id, result=cmd.get("result"))
                    print(f"[orchestrator] Research task {task_id} completed")

            elif cmd_type == "manual_command":
                # Commands from the API
                action = cmd.get("action")
                print(f"[orchestrator] Manual command: {action}")
                if action == "trigger_audit":
                    push_job(AUDIT_QUEUE, json.dumps({"type": "full_audit"}))
                elif action == "trigger_research":
                    codes = cmd.get("target_codes", [])
                    push_job(RESEARCH_QUEUE, json.dumps({
                        "type": "manual",
                        "target_codes": codes,
                    }))

            processed += 1
        except json.JSONDecodeError:
            print(f"[orchestrator] Invalid command JSON")
            processed += 1


def log_cycle(cycle_number, action_name, details, system_state):
    """Log an orchestrator cycle to the audit trail."""
    execute_query(
        """INSERT INTO research.orchestrator_log
           (cycle_number, action, details, system_state)
           VALUES (%s, %s, %s, %s)""",
        (
            cycle_number,
            action_name,
            json.dumps(details),
            json.dumps(system_state),
        )
    )


def run_cycle():
    """Execute one full OODA cycle."""
    global _cycle_number
    _cycle_number += 1

    start = time.time()

    # Process incoming commands first
    process_commands()

    # OODA loop
    observation = observe()
    situation = orient(observation)
    actions = decide(situation, observation)
    executed = act(actions, observation)

    duration_ms = int((time.time() - start) * 1000)

    # Log the cycle
    cycle_summary = {
        "situation": situation,
        "actions_decided": len(actions),
        "actions_executed": len(executed),
        "executed": executed,
        "duration_ms": duration_ms,
    }

    log_cycle(
        _cycle_number,
        "ooda_cycle",
        cycle_summary,
        observation["system_state"],
    )

    # Print summary (compact)
    queued = situation.get("total_queued", 0)
    idle = situation.get("pipeline_idle", False)
    action_strs = [e.get("action", "?") for e in executed]
    print(
        f"[orchestrator] Cycle #{_cycle_number} ({duration_ms}ms) "
        f"queued={queued} idle={idle} "
        f"actions={action_strs}"
    )


def main():
    print(
        f"[orchestrator] Started. Cycle={CYCLE_INTERVAL}s "
        f"AutoResearch={AUTO_RESEARCH}"
    )

    while True:
        try:
            run_cycle()
        except Exception as e:
            print(f"[orchestrator] ERROR in cycle: {e}")
            traceback.print_exc()

        time.sleep(CYCLE_INTERVAL)


if __name__ == "__main__":
    main()
