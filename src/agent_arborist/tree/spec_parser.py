"""Deterministic spec parser - parses structured markdown into TaskTree."""

from __future__ import annotations

import re
from pathlib import Path

from agent_arborist.tree.model import TaskNode, TaskTree


# Pattern: ## Phase N: Name
PHASE_PATTERN = re.compile(r"^##\s*Phase\s*(\d+):\s*(.+)$")

# Pattern: - [ ] T001 Description or - [ ] T001 [P] Description
TASK_PATTERN = re.compile(r"^-\s*\[\s*\]\s*(T\d+)\s*(\[P\])?\s*(.+)$")

# Dependency arrow: T001 → T002 or T001 → T002, T003
DEP_ARROW_PATTERN = re.compile(r"(T\d+)")


def parse_spec(path: Path, spec_id: str, namespace: str = "feature") -> TaskTree:
    """Parse a task spec markdown file into a TaskTree.

    Expects format with ## Phase N: headers, - [ ] TXXX task items,
    and a ## Dependencies section with arrow notation.
    """
    content = path.read_text()
    lines = content.strip().split("\n")

    tree = TaskTree(spec_id=spec_id, namespace=namespace)

    current_phase_id: str | None = None
    in_dependencies = False
    dep_lines: list[str] = []
    phase_counter = 0

    for line in lines:
        stripped = line.strip()

        if stripped == "## Dependencies":
            in_dependencies = True
            continue

        if in_dependencies:
            if stripped.startswith("## "):
                in_dependencies = False
            elif stripped and not stripped.startswith("```"):
                dep_lines.append(stripped)
            continue

        # Phase header
        if match := PHASE_PATTERN.match(stripped):
            phase_counter += 1
            phase_num = match.group(1)
            phase_name = match.group(2).strip()
            phase_id = f"phase{phase_num}"
            current_phase_id = phase_id

            tree.nodes[phase_id] = TaskNode(
                id=phase_id,
                name=phase_name,
            )
            tree.root_ids.append(phase_id)
            continue

        # Task item
        if match := TASK_PATTERN.match(stripped):
            task_id = match.group(1)
            description = match.group(3).strip()

            node = TaskNode(
                id=task_id,
                name=description,
                description=description,
                parent=current_phase_id,
            )

            tree.nodes[task_id] = node

            if current_phase_id and current_phase_id in tree.nodes:
                tree.nodes[current_phase_id].children.append(task_id)
            continue

    # Parse dependencies
    _parse_dependencies(dep_lines, tree)

    return tree


def _parse_dependencies(dep_lines: list[str], tree: TaskTree) -> None:
    """Parse dependency lines (T001 → T002 format) into the tree."""
    for line in dep_lines:
        if "Phase" in line or "Within" in line:
            continue

        parts = re.split(r"\s*→\s*", line)

        for i in range(1, len(parts)):
            prev_tasks = DEP_ARROW_PATTERN.findall(parts[i - 1])
            curr_tasks = DEP_ARROW_PATTERN.findall(parts[i])

            for curr in curr_tasks:
                if curr in tree.nodes:
                    for prev in prev_tasks:
                        if prev not in tree.nodes[curr].depends_on:
                            tree.nodes[curr].depends_on.append(prev)
