# Copyright 2026 Pennyworth Technologies, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

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

REQUIREMENT MAPPING:
If a file named test-plan.json exists in the spec directory (or any subdirectory like quality/),
OR if files in a quality/artifacts/ subdirectory contain parsed requirements:
1. Read the requirements to understand the requirement IDs (e.g. REQ-001, REQ-002)
2. For each LEAF task, include a "requirement_ids" array listing which requirement IDs
   that task implements or contributes to
3. A leaf task may map to zero, one, or multiple requirement IDs
4. Multiple leaf tasks may map to the same requirement ID (that is fine)
5. Every requirement ID from the specs SHOULD appear on at least one leaf task

Do NOT include "test_commands" in your output. Test commands will be merged
automatically from test-plan.json in a post-processing step.

Example leaf task with requirement_ids:
{{
  "id": "T005",
  "description": "Create SQLite schema with todos table",
  "parent": "Phase2",
  "source_file": "elaboration/tasks.md",
  "source_line": 10,
  "requirement_ids": ["REQ-005", "REQ-006"]
}}

FALLBACK (when NO test-plan.json or requirements exist):
For each leaf task, you may optionally include a "test_commands" array. Each entry:
{{
  "type": "unit" | "integration" | "e2e",
  "command": "shell command to run tests",
  "framework": "pytest" | "jest" | "vitest" | "go" | null,
  "timeout": <seconds or null>
}}
Infer the framework from project context (package.json, pyproject.toml, go.mod).

OUTPUT ONLY valid JSON. Start with {{ on line 1. No markdown fences.
No explanatory text before or after the JSON. ONLY the JSON object.
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

    logger.debug("Raw AI output:\n%s", result.output)
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

    # Deterministically merge test commands from test-plan.json
    _merge_test_plan(tree, spec_dir)

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
            requirement_ids=t.get("requirement_ids", []),
        )

    if not tree.nodes:
        return None

    tree.spec_files = sorted(
        {n.source_file for n in tree.nodes.values() if n.source_file}
    )

    return tree


def _find_test_plan(spec_dir: Path) -> Path | None:
    """Search for test-plan.json in the spec directory hierarchy.

    Searches in order:
    1. spec_dir/quality/test-plan.json (factory pipeline convention)
    2. spec_dir/test-plan.json (flat layout)
    3. Any test-plan.json in immediate subdirectories
    """
    candidates = [
        spec_dir / "quality" / "test-plan.json",
        spec_dir / "test-plan.json",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate

    for subdir in spec_dir.iterdir():
        if subdir.is_dir():
            candidate = subdir / "test-plan.json"
            if candidate.is_file():
                return candidate

    return None


def _merge_test_plan(tree: TaskTree, spec_dir: Path) -> None:
    """Deterministically merge test commands from test-plan.json into the task tree.

    For each leaf node with requirement_ids, finds all tests from test-plan.json
    whose requirement_ids overlap, and creates TestCommand objects attached to
    the leaf node's test_commands list.

    Mutates tree in place. If no test-plan.json is found, does nothing.
    """
    test_plan_path = _find_test_plan(spec_dir)
    if test_plan_path is None:
        logger.debug("No test-plan.json found in %s, skipping merge", spec_dir)
        return

    try:
        with open(test_plan_path) as f:
            plan_data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to read test-plan.json at %s: %s", test_plan_path, e)
        return

    tests = plan_data.get("tests", [])
    if not tests:
        logger.debug("test-plan.json has no tests, skipping merge")
        return

    # Build index: requirement_id -> list of test dicts
    req_to_tests: dict[str, list[dict]] = {}
    for test in tests:
        for req_id in test.get("requirement_ids", []):
            req_to_tests.setdefault(req_id, []).append(test)

    # For each leaf node with requirement_ids, collect matching tests
    merged_count = 0
    all_matched_test_ids: set[str] = set()

    for node in tree.nodes.values():
        if not node.is_leaf or not node.requirement_ids:
            continue

        # Collect tests matching any of this node's requirement_ids
        # Use dict keyed by test_id to deduplicate
        matched_tests: dict[str, dict] = {}
        for req_id in node.requirement_ids:
            for test in req_to_tests.get(req_id, []):
                tid = test.get("test_id", "")
                if tid and tid not in matched_tests:
                    matched_tests[tid] = test

        # Convert to TestCommand objects, sorted by test_id for determinism
        test_commands = []
        for test_id in sorted(matched_tests.keys()):
            test = matched_tests[test_id]
            try:
                tc = TestCommand(
                    type=TestType(test.get("test_type", "unit")),
                    command=test.get("command", ""),
                    framework=test.get("framework"),
                    timeout=test.get("timeout_s"),
                    test_id=test.get("test_id"),
                    name=test.get("name"),
                )
                test_commands.append(tc)
                all_matched_test_ids.add(test_id)
            except (KeyError, ValueError) as e:
                logger.warning(
                    "Skipping invalid test %s for node %s: %s",
                    test.get("test_id", "?"), node.id, e,
                )

        node.test_commands = test_commands
        merged_count += len(test_commands)

    # Warn about orphaned tests not matched to any task
    all_test_ids = {t.get("test_id") for t in tests if t.get("test_id")}
    orphaned = all_test_ids - all_matched_test_ids
    if orphaned:
        logger.warning(
            "%d tests from test-plan.json not matched to any task: %s",
            len(orphaned), sorted(orphaned)[:10],
        )

    logger.info(
        "Merged %d test commands from %s across %d leaf nodes",
        merged_count,
        test_plan_path.name,
        sum(1 for n in tree.nodes.values() if n.is_leaf and n.test_commands),
    )


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
