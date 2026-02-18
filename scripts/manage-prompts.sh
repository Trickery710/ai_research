#!/bin/bash
# =============================================================================
# Agent Prompt Manager for AI Research Refinery
#
# View, compare, and apply prompt changes from config/prompts.yaml
# to the worker source files.
#
# Usage:
#   ./scripts/manage-prompts.sh show [agent]    Show current prompts
#   ./scripts/manage-prompts.sh diff            Compare config vs source
#   ./scripts/manage-prompts.sh apply           Write config prompts to source
#   ./scripts/manage-prompts.sh list            List all agents with prompts
# =============================================================================

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG_FILE="$PROJECT_DIR/config/prompts.yaml"

# Map agent names to source files
declare -A SOURCE_FILES=(
    [extraction]="workers/extraction/worker.py"
    [evaluation]="workers/evaluation/worker.py"
    [healing]="workers/healing/analyzer.py"
    [verification]="workers/verify/worker.py"
    [research_gap]="workers/researcher/gap_analyzer.py"
    [research_query]="workers/researcher/query_generator.py"
)

declare -A LLM_MODELS=(
    [extraction]="llm-reason (gemma3:12b, RTX 3080, temp=0.1)"
    [evaluation]="llm-eval (gemma3:12b, RTX 3070, temp=0.2)"
    [healing]="llm-reason (gemma3:12b, RTX 3080, temp=0.2)"
    [verification]="OpenAI gpt-4o-mini (external API)"
    [research_gap]="llm-reason (gemma3:12b, RTX 3080)"
    [research_query]="llm-reason (gemma3:12b, RTX 3080)"
)

declare -A DESCRIPTIONS=(
    [extraction]="Extract DTC codes, causes, diagnostic steps, sensors, TSBs, vehicles from text"
    [evaluation]="Score chunk trust (credibility) and relevance (diagnostic utility)"
    [healing]="Analyze system alerts and propose safe auto-remediation actions"
    [verification]="Cross-verify DTC data accuracy against OpenAI knowledge"
    [research_gap]="Identify knowledge gaps and generate research search queries"
    [research_query]="Generate URLs for specific DTC codes from trusted domains"
)

show_prompt() {
    local agent="$1"
    local file="${SOURCE_FILES[$agent]:-}"

    if [ -z "$file" ]; then
        echo "Unknown agent: $agent"
        echo "Available: ${!SOURCE_FILES[*]}"
        return 1
    fi

    echo "=============================================="
    echo "Agent: $agent"
    echo "Source: $file"
    echo "LLM:   ${LLM_MODELS[$agent]}"
    echo "Role:  ${DESCRIPTIONS[$agent]}"
    echo "=============================================="
    echo ""

    local fullpath="$PROJECT_DIR/$file"
    if [ ! -f "$fullpath" ]; then
        echo "  Source file not found: $fullpath"
        return 1
    fi

    # Extract prompt strings from Python source
    echo "--- SYSTEM PROMPT ---"
    # Look for SYSTEM_PROMPT or system_prompt variable assignment
    python3 -c "
import ast, sys

with open('$fullpath') as f:
    source = f.read()

tree = ast.parse(source)
for node in ast.walk(tree):
    if isinstance(node, ast.Assign):
        for target in node.targets:
            name = getattr(target, 'id', '') or ''
            if 'SYSTEM_PROMPT' in name.upper() or 'SYSTEM_PROMPT' in name:
                if isinstance(node.value, (ast.Constant, ast.Str)):
                    val = node.value.value if hasattr(node.value, 'value') else node.value.s
                    print(val)
                    sys.exit(0)

# Fallback: search for triple-quoted strings containing key phrases
import re
prompts = re.findall(r'\"\"\"(.*?)\"\"\"', source, re.DOTALL)
for p in prompts:
    if 'JSON' in p or 'extract' in p.lower() or 'evaluate' in p.lower() or 'verify' in p.lower():
        print(p.strip())
        break
" 2>/dev/null || echo "  (could not extract - check source file manually)"

    echo ""
    echo "--- USER PROMPT TEMPLATE ---"
    python3 -c "
import re

with open('$fullpath') as f:
    source = f.read()

# Look for f-string prompt construction
patterns = [
    r'prompt\s*=\s*\(\s*f?\"(.*?)\"',
    r'prompt\s*=\s*\(\s*f?\"\"\"(.*?)\"\"\"',
    r'user_prompt\s*=\s*f?\"\"\"(.*?)\"\"\"',
]
for pat in patterns:
    m = re.search(pat, source, re.DOTALL)
    if m:
        print(m.group(1).strip())
        break
else:
    # Show lines containing 'prompt' for manual review
    for i, line in enumerate(source.split('\n'), 1):
        if 'prompt' in line.lower() and '=' in line and '#' not in line[:line.find('prompt')]:
            print(f'  Line {i}: {line.strip()}')
" 2>/dev/null || echo "  (could not extract)"

    echo ""
}

list_agents() {
    echo "=============================================="
    echo "AI Research Refinery - Agent Prompts"
    echo "=============================================="
    echo ""
    printf "%-18s %-45s %s\n" "AGENT" "SOURCE FILE" "LLM"
    printf "%-18s %-45s %s\n" "-----" "-----------" "---"
    for agent in extraction evaluation healing verification research_gap research_query; do
        printf "%-18s %-45s %s\n" "$agent" "${SOURCE_FILES[$agent]}" "${LLM_MODELS[$agent]}"
    done
    echo ""
    echo "Config file: config/prompts.yaml"
    echo ""
    echo "Use '$0 show <agent>' to see the full prompt"
    echo "Use '$0 diff' to compare config vs source"
}

diff_prompts() {
    echo "Comparing config/prompts.yaml against worker source files..."
    echo ""

    if [ ! -f "$CONFIG_FILE" ]; then
        echo "Config file not found: $CONFIG_FILE"
        echo "Create it first, or run '$0 show <agent>' to see current prompts."
        return 1
    fi

    local any_diff=false
    for agent in extraction evaluation healing verification research_gap research_query; do
        local file="$PROJECT_DIR/${SOURCE_FILES[$agent]}"
        if [ ! -f "$file" ]; then
            continue
        fi

        # Extract config prompt via python
        local config_prompt
        config_prompt=$(python3 -c "
import yaml
with open('$CONFIG_FILE') as f:
    cfg = yaml.safe_load(f)
agent_cfg = cfg.get('$agent', {})
sp = agent_cfg.get('system_prompt', '')
if sp:
    print(sp.strip())
" 2>/dev/null || true)

        if [ -z "$config_prompt" ]; then
            continue
        fi

        # Extract source prompt
        local source_prompt
        source_prompt=$(python3 -c "
import ast
with open('$file') as f:
    source = f.read()
tree = ast.parse(source)
for node in ast.walk(tree):
    if isinstance(node, ast.Assign):
        for target in node.targets:
            name = getattr(target, 'id', '') or ''
            if 'SYSTEM_PROMPT' in name.upper():
                if isinstance(node.value, (ast.Constant, ast.Str)):
                    val = node.value.value if hasattr(node.value, 'value') else node.value.s
                    print(val.strip())
" 2>/dev/null || true)

        if [ -z "$source_prompt" ]; then
            continue
        fi

        # Compare
        local diff_result
        diff_result=$(diff <(echo "$config_prompt") <(echo "$source_prompt") 2>/dev/null || true)

        if [ -n "$diff_result" ]; then
            echo "DIFFERS: $agent (${SOURCE_FILES[$agent]})"
            echo "$diff_result" | head -20
            echo ""
            any_diff=true
        fi
    done

    if [ "$any_diff" = false ]; then
        echo "All prompts match between config and source files."
    fi
}

apply_prompts() {
    echo "This will overwrite system prompts in worker source files"
    echo "with values from config/prompts.yaml."
    echo ""
    read -p "Continue? [y/N] " confirm
    if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
        echo "Aborted."
        return 0
    fi

    if [ ! -f "$CONFIG_FILE" ]; then
        echo "Config file not found: $CONFIG_FILE"
        return 1
    fi

    python3 - "$CONFIG_FILE" "$PROJECT_DIR" <<'PYEOF'
import sys
import yaml
import re

config_file = sys.argv[1]
project_dir = sys.argv[2]

SOURCE_MAP = {
    "extraction": "workers/extraction/worker.py",
    "evaluation": "workers/evaluation/worker.py",
    "healing": "workers/healing/analyzer.py",
    "verification": "workers/verify/worker.py",
}

with open(config_file) as f:
    cfg = yaml.safe_load(f)

for agent, rel_path in SOURCE_MAP.items():
    agent_cfg = cfg.get(agent, {})
    new_prompt = agent_cfg.get("system_prompt", "").strip()
    if not new_prompt:
        continue

    filepath = f"{project_dir}/{rel_path}"
    try:
        with open(filepath) as f:
            source = f.read()
    except FileNotFoundError:
        print(f"  SKIP: {rel_path} (file not found)")
        continue

    # Find and replace the SYSTEM_PROMPT string
    # Match: SYSTEM_PROMPT = """...""" or SYSTEM_PROMPT = "..."
    pattern = r'(SYSTEM_PROMPT\s*=\s*""")(.*?)(""")'
    match = re.search(pattern, source, re.DOTALL)

    if match:
        old_prompt = match.group(2).strip()
        if old_prompt == new_prompt:
            print(f"  UNCHANGED: {agent} ({rel_path})")
            continue

        new_source = source[:match.start(2)] + new_prompt + "\n" + source[match.end(2):]
        with open(filepath, "w") as f:
            f.write(new_source)
        print(f"  UPDATED: {agent} ({rel_path})")
    else:
        print(f"  SKIP: {agent} - could not find SYSTEM_PROMPT in {rel_path}")

print()
print("Done. Rebuild affected workers:")
print("  docker compose build worker-extraction worker-evaluation healing-agent worker-verify")
print("  docker compose up -d worker-extraction worker-evaluation healing-agent worker-verify")
PYEOF
}

# Main
case "${1:-help}" in
    show)
        if [ -z "${2:-}" ]; then
            echo "Usage: $0 show <agent>"
            echo "Agents: ${!SOURCE_FILES[*]}"
            exit 1
        fi
        show_prompt "$2"
        ;;
    list)
        list_agents
        ;;
    diff)
        diff_prompts
        ;;
    apply)
        apply_prompts
        ;;
    help|--help|-h)
        echo "Agent Prompt Manager - AI Research Refinery"
        echo ""
        echo "Usage:"
        echo "  $0 list              List all agents and their LLM assignments"
        echo "  $0 show <agent>      Show the current prompt for an agent"
        echo "  $0 diff              Compare config/prompts.yaml vs source files"
        echo "  $0 apply             Write config prompts to worker source files"
        echo ""
        echo "Workflow:"
        echo "  1. Edit config/prompts.yaml"
        echo "  2. Run '$0 diff' to review changes"
        echo "  3. Run '$0 apply' to write to source files"
        echo "  4. Rebuild and restart affected workers"
        echo ""
        echo "Agents: ${!SOURCE_FILES[*]}"
        ;;
    *)
        echo "Unknown command: $1 (use --help)"
        exit 1
        ;;
esac
