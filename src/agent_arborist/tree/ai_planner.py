"""AI-assisted task tree generation from spec directories."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

from agent_arborist.runner import Runner, get_runner, RunnerType, DAG_DEFAULT_RUNNER, DAG_DEFAULT_MODEL
from agent_arborist.tree.model import TaskNode, TaskTree, TestCommand, TestType


TASK_ANALYSIS_PROMPT = '''Extract the COMPLETE task tree from the task specification files.

The task specification files are in the directory: {spec_dir}
Read all files in that directory to understand the task specification.

Extract the FULL TREE of tasks WITH their natural groupings from the spec files.

DETECTING HIERARCHY:
Look for natural groupings in the spec such as:
- Markdown headers (## Phase 1, ### User Story 1)
- Numbered sections (1. Setup, 2. Implementation)
- Named groups (Phase 1:, Story 1:, Step 1:)
- Indentation showing nesting

These groupings become PARENT TASKS with child tasks beneath them.

OUTPUT FORMAT - JSON:
{{
  "description": "Brief Project Description",
  "total_tasks_found": <INTEGER - count ALL tasks including parent groupings>,
  "tasks": [
    {{
      "id": "Phase1",
      "description": "Phase 1: Setup",
      "children": ["T001", "T002", "T003"]
    }},
    {{
      "id": "T001",
      "description": "Create directory structure",
      "parent": "Phase1",
      "source_file": "tasks.md",
      "source_line": 10
    }},
    {{
      "id": "Phase2",
      "description": "Phase 2: Implementation",
      "children": ["SubGroup1", "T005"]
    }},
    {{
      "id": "SubGroup1",
      "description": "Sub-group: API layer",
      "parent": "Phase2",
      "children": ["T004"]
    }},
    {{
      "id": "T004",
      "description": "Implement feature",
      "parent": "SubGroup1"
    }}
  ]
}}

TREE STRUCTURE:
1. Groupings (phases, stories, sections) become parent tasks with "children" array
2. Leaf tasks have "parent" pointing to their containing group
3. Top-level groupings have NO parent (they are root tasks)
4. Leaf tasks have NO children
5. Nesting to arbitrary depth is allowed (e.g. Phase → SubGroup → Task)

SOURCE REFERENCES:
- For each task, include "source_file" (relative path of the spec file) and "source_line" (1-indexed line number where the task appears)

EXTRACTION RULES:
1. Extract EVERY single task - count must match all task items in the spec
2. Preserve original descriptions exactly as written
3. Handle flexible ID formats: if no IDs exist, generate sequential ones (T001, T002, ...)
4. For groupings without IDs, generate: Phase1, Phase2, Story1, etc.
5. Support various markdown patterns:
   - Checkbox lists: "- [ ] description"
   - Numbered lists: "1. description"
   - Plain lists: "- description"
   - Labeled items: "T001: description"
6. Infer hierarchy from:
   - Markdown header levels (## > ###)
   - Indentation levels
   - Explicit "Phase X" or "Story X" labels
   - Section boundaries

TEST COMMANDS:
For each task, optionally generate a "test_commands" array. Each entry:
{{
  "type": "unit" | "integration" | "e2e",
  "command": "shell command to run tests",
  "framework": "pytest" | "jest" | "vitest" | "go" | null,
  "timeout": <seconds or null>
}}

Rules:
- Leaf tasks typically get "type": "unit" tests
- Parent/group tasks may get "type": "integration" or "type": "e2e" tests
- Integration/e2e tests on parent nodes run after all child tasks complete
- Infer the framework from project context (package.json → jest/vitest, pyproject.toml → pytest, go.mod → go)
- If you cannot determine a test command, omit test_commands (it defaults to empty)

Framework template examples:
- pytest: {{"type": "unit", "command": "python -m pytest tests/ -x", "framework": "pytest"}}
- jest: {{"type": "unit", "command": "npx jest --passWithNoTests", "framework": "jest"}}
- vitest: {{"type": "unit", "command": "npx vitest run", "framework": "vitest"}}
- go: {{"type": "unit", "command": "go test ./...", "framework": "go"}}
- cargo: {{"type": "unit", "command": "cargo test", "framework": "cargo"}}

OUTPUT ONLY valid JSON. Start with {{ on line 1. No markdown fences.
'''


@dataclass
class PlanResult:
    success: bool
    tree: TaskTree | None = None
    error: str | None = None
    raw_output: str | None = None


def plan_tree(
    spec_dir: Path,
    timeout: int,
    runner: Runner | None = None,
    runner_type: RunnerType = DAG_DEFAULT_RUNNER,
    model: str = DAG_DEFAULT_MODEL,
    container_workspace: Path | None = None,
) -> PlanResult:
    """Use AI to generate a TaskTree from a spec directory."""
    runner_instance = runner or get_runner(runner_type, model)

    logger.info("Planning tree from spec files in %s", spec_dir)
    prompt = TASK_ANALYSIS_PROMPT.format(spec_dir=spec_dir)
    result = runner_instance.run(prompt, timeout=timeout,
                                 container_workspace=container_workspace)

    if not result.success:
        return PlanResult(
            success=False,
            error=result.error or "Runner failed",
            raw_output=result.output,
        )

    logger.debug("Extracting JSON from output")
    task_json = _extract_json(result.output)
    if not task_json:
        return PlanResult(
            success=False,
            error="Could not extract valid JSON from AI output",
            raw_output=result.output,
        )

    try:
        data = json.loads(task_json)
    except json.JSONDecodeError as e:
        return PlanResult(
            success=False,
            error=f"Invalid JSON: {e}",
            raw_output=result.output,
        )

    if "tasks" not in data or not isinstance(data["tasks"], list):
        return PlanResult(
            success=False,
            error="JSON missing 'tasks' array",
            raw_output=result.output,
        )

    tree = _build_tree_from_json(data)
    if tree is None:
        return PlanResult(
            success=False,
            error="No valid tasks found in JSON",
            raw_output=result.output,
        )

    logger.info("Planning complete: %d nodes", len(tree.nodes))
    return PlanResult(success=True, tree=tree, raw_output=result.output)



def _build_tree_from_json(
    data: dict,
) -> TaskTree | None:
    """Build a TaskTree from the AI-generated JSON structure."""
    tree = TaskTree()

    for t in data["tasks"]:
        if "id" not in t:
            continue
        tid = t["id"]
        test_commands = []
        for tc_data in t.get("test_commands", []):
            try:
                test_commands.append(TestCommand.from_dict(tc_data))
            except (KeyError, ValueError):
                logger.warning("Skipping invalid test_command in task %s", tid)

        tree.nodes[tid] = TaskNode(
            id=tid,
            name=t.get("description", tid),
            description=t.get("description", tid),
            parent=t.get("parent"),
            children=t.get("children", []),
            depends_on=t.get("depends_on", []),
            source_file=t.get("source_file"),
            source_line=t.get("source_line"),
            test_commands=test_commands,
        )

    if not tree.nodes:
        return None

    tree.spec_files = sorted(
        {n.source_file for n in tree.nodes.values() if n.source_file}
    )

    return tree


def _extract_json(output: str) -> str | None:
    """Extract JSON content from AI output."""
    # Try code blocks first
    matches = re.findall(r"```(?:json)?\s*\n(.*?)```", output, re.DOTALL)
    if matches:
        return matches[0].strip()

    # Try to find content starting with {
    lines = output.strip().split("\n")
    for i, line in enumerate(lines):
        if line.strip().startswith("{"):
            content = "\n".join(lines[i:])
            brace_count = 0
            for j, char in enumerate(content):
                if char == "{":
                    brace_count += 1
                elif char == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        return content[: j + 1]
            break

    return None
