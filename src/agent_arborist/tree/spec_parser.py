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

"""Deterministic spec parser - parses structured markdown into TaskTree."""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

from agent_arborist.tree.model import TaskNode, TaskTree


# Pattern: ## Phase N: Name
PHASE_PATTERN = re.compile(r"^##\s*Phase\s*(\d+):\s*(.+)$")

# Pattern: ### or #### etc. subgroup headers
SUBGROUP_PATTERN = re.compile(r"^(#{3,6})\s+(.+)$")

# Pattern: - [ ] T001 Description or - [ ] T001 [P] Description
TASK_PATTERN = re.compile(r"^-\s*\[\s*\]\s*(T\d+)\s*(\[P\])?\s*(.+)$")

# Dependency arrow: T001 → T002 or T001 → T002, T003
DEP_ARROW_PATTERN = re.compile(r"(T\d+)")


def parse_spec(path: Path) -> TaskTree:
    """Parse a task spec markdown file into a TaskTree.

    Expects format with ## Phase N: headers, - [ ] TXXX task items,
    and a ## Dependencies section with arrow notation.
    """
    content = path.read_text()
    lines = content.strip().split("\n")

    tree = TaskTree()
    rel_path = str(path)
    tree.spec_files = [rel_path]

    # Stack tracks (header_level, node_id) for nested groups.
    # Level 2 = phase (##), level 3 = ### subgroup, etc.
    group_stack: list[tuple[int, str]] = []
    in_dependencies = False
    dep_lines: list[str] = []
    subgroup_counter = 0

    def _current_group_id() -> str | None:
        return group_stack[-1][1] if group_stack else None

    def _pop_to_level(level: int) -> None:
        """Pop stack entries at or deeper than the given level."""
        while group_stack and group_stack[-1][0] >= level:
            group_stack.pop()

    for line_idx, line in enumerate(lines):
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

        # Phase header (## Phase N: Name)
        if match := PHASE_PATTERN.match(stripped):
            _pop_to_level(2)
            phase_num = match.group(1)
            phase_name = match.group(2).strip()
            phase_id = f"phase{phase_num}"

            logger.debug("Phase %s: %s", phase_id, phase_name)
            tree.nodes[phase_id] = TaskNode(
                id=phase_id,
                name=phase_name,
                source_file=rel_path,
                source_line=line_idx + 1,
            )
            group_stack.append((2, phase_id))
            continue

        # Subgroup header (### or deeper)
        if match := SUBGROUP_PATTERN.match(stripped):
            level = len(match.group(1))  # number of #'s
            subgroup_name = match.group(2).strip()
            subgroup_counter += 1
            subgroup_id = f"group{subgroup_counter}"

            _pop_to_level(level)
            parent_id = _current_group_id()

            tree.nodes[subgroup_id] = TaskNode(
                id=subgroup_id,
                name=subgroup_name,
                parent=parent_id,
                source_file=rel_path,
                source_line=line_idx + 1,
            )

            if parent_id and parent_id in tree.nodes:
                tree.nodes[parent_id].children.append(subgroup_id)

            group_stack.append((level, subgroup_id))
            continue

        # Task item
        if match := TASK_PATTERN.match(stripped):
            task_id = match.group(1)
            description = match.group(3).strip()
            parent_id = _current_group_id()

            node = TaskNode(
                id=task_id,
                name=description,
                description=description,
                parent=parent_id,
                source_file=rel_path,
                source_line=line_idx + 1,
            )

            logger.debug("Task %s: %s (parent=%s)", task_id, description, parent_id)
            tree.nodes[task_id] = node

            if parent_id and parent_id in tree.nodes:
                tree.nodes[parent_id].children.append(task_id)
            continue

    # Parse dependencies
    _parse_dependencies(dep_lines, tree)

    logger.info("Parsed spec: %d nodes from %s", len(tree.nodes), path.name)
    logger.debug("Root IDs: %s", tree.root_ids)
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
