"""LLM-powered error analysis and fix strategy generation."""

import sys
import os
import json
from typing import Dict, Optional

sys.path.insert(0, "/app")

from shared.ollama_client import generate_completion

SYSTEM_PROMPT = """You are an expert DevOps and SRE engineer specializing in
distributed document processing pipelines. You analyze system alerts and propose
precise, safe remediation strategies.

Given an alert, respond with ONLY a JSON object (no other text):

{
  "action": "<action_identifier>",
  "confidence": <float 0.0-1.0>,
  "reasoning": "<detailed explanation of the problem and why this fix will work>",
  "parameters": {<optional params for the action>},
  "alternative_actions": ["<backup_action_1>", "<backup_action_2>"]
}

Available actions:
- restart_worker:<worker_name>         # Restart a specific worker container
- restart_container:<container_name>   # Restart any container
- requeue_documents:<stage>            # Re-queue stuck documents from a stage
- clear_stale_locks                    # Clear Redis locks older than 1 hour
- analyze_errors:<stage>               # Deep dive into error logs (no auto-fix)
- check_resource_usage:<component>     # Check CPU/memory (no auto-fix)
- escalate_to_human                    # Cannot auto-fix, needs human review

Guidelines:
- Choose the LEAST disruptive action that solves the problem
- confidence should reflect certainty (0.9+ for well-understood issues, <0.7 for ambiguous)
- If the issue is unclear or risky, choose "escalate_to_human" with low confidence
- For stuck queues with working workers, try requeue_documents before restart_worker
- For unhealthy containers, restart is usually safe
- NEVER propose actions that delete data or modify the database schema
"""


def parse_llm_response(response_text: str) -> Optional[Dict]:
    """Parse LLM JSON response with fallback strategies."""
    text = response_text.strip()

    # Strategy 1: direct JSON parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Strategy 2: extract from ```json code block
    if "```json" in text:
        try:
            start = text.index("```json") + 7
            end = text.index("```", start)
            return json.loads(text[start:end].strip())
        except (json.JSONDecodeError, ValueError):
            pass

    # Strategy 3: find outermost braces
    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last > first:
        try:
            return json.loads(text[first:last + 1])
        except json.JSONDecodeError:
            pass

    return None


def analyze_alert_with_llm(alert: Dict) -> Optional[Dict]:
    """Use Ollama LLM to analyze an alert and propose a fix strategy."""

    # Format alert as structured prompt
    alert_summary = f"""
ALERT DETAILS:
- ID: {alert.get('id')}
- Type: {alert.get('type')}
- Severity: {alert.get('severity')}
- Component: {alert.get('component')}
- Details: {alert.get('details')}
- Recommended Action (from detector): {alert.get('recommended_action', 'none')}

ADDITIONAL CONTEXT:
{json.dumps(alert, indent=2)}

Analyze this alert and propose the best remediation action.
"""

    try:
        response_text = generate_completion(
            prompt=alert_summary,
            system_prompt=SYSTEM_PROMPT,
            format_json=True,
            temperature=0.1,  # Low temperature for deterministic, conservative decisions
            model=os.environ.get("REASONING_MODEL", "llama3")
        )

        result = parse_llm_response(response_text)

        if result and 'action' in result:
            # Validate response structure
            if 'confidence' not in result:
                result['confidence'] = 0.5
            if 'reasoning' not in result:
                result['reasoning'] = 'No reasoning provided'

            return result
        else:
            return None

    except Exception as e:
        print(f"[analyzer] LLM analysis failed: {e}")
        return None
