"""AI-assisted task tree generation from spec directories."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

from agent_arborist.runner import Runner, get_runner, RunnerType, DAG_DEFAULT_RUNNER, DAG_DEFAULT_MODEL
from agent_arborist.tree.model import TaskNode, TaskTree


TASK_ANALYSIS_PROMPT = '''Extract the COMPLETE task tree from the task specification files.

TASK SPECIFICATION DIRECTORY: {spec_dir}

SPEC FILE CONTENTS (with line numbers):
{spec_contents}

Extract the FULL TREE of tasks WITH their natural groupings from the spec files above.

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
    spec_id: str,
    namespace: str = "feature",
    runner: Runner | None = None,
    runner_type: RunnerType = DAG_DEFAULT_RUNNER,
    model: str = DAG_DEFAULT_MODEL,
    timeout: int = 120,
) -> PlanResult:
    """Use AI to generate a TaskTree from a spec directory."""
    runner_instance = runner or get_runner(runner_type, model)

    spec_files = list(spec_dir.glob("*.md"))
    logger.info("Planning tree from %d spec files in %s", len(spec_files), spec_dir)
    spec_contents = _read_spec_contents(spec_dir)
    prompt = TASK_ANALYSIS_PROMPT.format(
        spec_dir=spec_dir.resolve(),
        spec_contents=spec_contents,
    )
    logger.debug("Prompt length: %d chars", len(prompt))
    result = runner_instance.run(prompt, timeout=timeout, cwd=spec_dir)

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

    tree = _build_tree_from_json(data, spec_id, namespace)
    if tree is None:
        return PlanResult(
            success=False,
            error="No valid tasks found in JSON",
            raw_output=result.output,
        )

    logger.info("Planning complete: %d nodes", len(tree.nodes))
    return PlanResult(success=True, tree=tree, raw_output=result.output)


def _read_spec_contents(spec_dir: Path) -> str:
    """Read all markdown files in spec_dir with line numbers."""
    parts: list[str] = []
    for md in sorted(spec_dir.glob("*.md")):
        lines = md.read_text().splitlines()
        numbered = "\n".join(f"{i + 1}: {line}" for i, line in enumerate(lines))
        parts.append(f"--- {md.name} ---\n{numbered}")
    return "\n\n".join(parts) if parts else "(no spec files found)"


def _build_tree_from_json(
    data: dict, spec_id: str, namespace: str
) -> TaskTree | None:
    """Build a TaskTree from the AI-generated JSON structure."""
    tree = TaskTree(spec_id=spec_id, namespace=namespace)

    for t in data["tasks"]:
        if "id" not in t:
            continue
        tid = t["id"]
        tree.nodes[tid] = TaskNode(
            id=tid,
            name=t.get("description", tid),
            description=t.get("description", tid),
            parent=t.get("parent"),
            children=t.get("children", []),
            depends_on=t.get("depends_on", []),
            source_file=t.get("source_file"),
            source_line=t.get("source_line"),
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
