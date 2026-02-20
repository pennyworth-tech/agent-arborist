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

"""Task tree model - dataclasses for the task hierarchy."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum


class TestType(Enum):
    UNIT = "unit"
    INTEGRATION = "integration"
    E2E = "e2e"


@dataclass
class TestCommand:
    type: TestType
    command: str
    framework: str | None = None  # "pytest", "jest", "vitest", "go", etc.
    timeout: int | None = None

    def to_dict(self) -> dict:
        result = {"type": self.type.value, "command": self.command}
        if self.framework is not None:
            result["framework"] = self.framework
        if self.timeout is not None:
            result["timeout"] = self.timeout
        return result

    @classmethod
    def from_dict(cls, data: dict) -> TestCommand:
        return cls(
            type=TestType(data["type"]),
            command=data["command"],
            framework=data.get("framework"),
            timeout=data.get("timeout"),
        )


@dataclass
class TaskNode:
    id: str
    name: str
    description: str = ""
    parent: str | None = None
    children: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    source_file: str | None = None
    source_line: int | None = None
    test_commands: list[TestCommand] = field(default_factory=list)

    @property
    def is_leaf(self) -> bool:
        return len(self.children) == 0


@dataclass
class TaskTree:
    nodes: dict[str, TaskNode] = field(default_factory=dict)
    execution_order: list[str] = field(default_factory=list)
    spec_files: list[str] = field(default_factory=list)

    @property
    def root_ids(self) -> list[str]:
        return [nid for nid, n in self.nodes.items() if n.parent is None]

    def leaves(self) -> list[TaskNode]:
        return [n for n in self.nodes.values() if n.is_leaf]

    def ready_leaves(self, completed: set[str]) -> list[TaskNode]:
        ready = []
        for node in self.leaves():
            if node.id in completed:
                continue
            if all(d in completed for d in node.depends_on):
                ready.append(node)
        return ready

    def root_phase(self, node_id: str) -> str:
        """Walk up to the topmost ancestor (parent is None)."""
        nid = node_id
        while True:
            parent = self.nodes[nid].parent
            if parent is None:
                return nid
            nid = parent

    def leaves_under(self, node_id: str) -> list[TaskNode]:
        """Recursively collect all leaf descendants of node_id."""
        node = self.nodes[node_id]
        if node.is_leaf:
            return [node]
        result: list[TaskNode] = []
        for child_id in node.children:
            result.extend(self.leaves_under(child_id))
        return result

    def _structural_sort_key(self, node_id: str) -> tuple:
        """Return a sort key that respects tree structure order.

        Produces (root_index, child_index_path...) so that tasks under M2
        sort before tasks under M10, matching the order roots and children
        appear in the tree rather than lexicographic order.
        """
        # Walk up to build the path from root to this node
        path = [node_id]
        nid = node_id
        while self.nodes[nid].parent is not None:
            nid = self.nodes[nid].parent
            path.append(nid)
        path.reverse()  # root first

        # Convert each level to its index among siblings
        key: list[int] = []
        root_ids = self.root_ids
        root = path[0]
        key.append(root_ids.index(root) if root in root_ids else 0)
        for i in range(1, len(path)):
            parent = self.nodes[path[i - 1]]
            child = path[i]
            key.append(parent.children.index(child) if child in parent.children else 0)
        return tuple(key)

    def compute_execution_order(self) -> list[str]:
        """Compute topological execution order using Kahn's algorithm.

        Only includes leaf tasks (actual work items).
        Ties are broken by structural tree order (root_ids and children
        ordering) so that e.g. M2 tasks execute before M10 tasks.
        """
        leaves = [n.id for n in self.leaves()]

        # Build in-degree map for leaf dependencies
        in_degree: dict[str, int] = {}
        dependents: dict[str, list[str]] = {}

        for nid in leaves:
            node = self.nodes[nid]
            # Only count dependencies that are also leaves
            deps = [d for d in node.depends_on if d in leaves]
            in_degree[nid] = len(deps)
            for d in deps:
                dependents.setdefault(d, []).append(nid)

        # Kahn's: start with nodes that have no dependencies
        # Use sorted order to break ties by structural position
        ready = sorted(
            (nid for nid, deg in in_degree.items() if deg == 0),
            key=self._structural_sort_key,
        )
        queue = deque(ready)
        order: list[str] = []

        while queue:
            nid = queue.popleft()
            order.append(nid)
            newly_ready = []
            for dep in dependents.get(nid, []):
                in_degree[dep] -= 1
                if in_degree[dep] == 0:
                    newly_ready.append(dep)
            newly_ready.sort(key=self._structural_sort_key)
            queue.extend(newly_ready)

        self.execution_order = order
        return order

    def to_dict(self) -> dict:
        return {
            "nodes": {
                nid: {
                    "id": n.id,
                    "name": n.name,
                    "description": n.description,
                    "parent": n.parent,
                    "children": n.children,
                    "depends_on": n.depends_on,
                    "source_file": n.source_file,
                    "source_line": n.source_line,
                    "is_leaf": n.is_leaf,
                    "test_commands": [tc.to_dict() for tc in n.test_commands],
                }
                for nid, n in self.nodes.items()
            },
            "root_ids": self.root_ids,
            "execution_order": self.execution_order,
            "spec_files": self.spec_files,
        }

    @classmethod
    def from_dict(cls, data: dict) -> TaskTree:
        tree = cls(
            execution_order=data.get("execution_order", []),
            spec_files=data.get("spec_files", []),
        )
        for nid, nd in data.get("nodes", {}).items():
            tree.nodes[nid] = TaskNode(
                id=nd["id"],
                name=nd["name"],
                description=nd.get("description", ""),
                parent=nd.get("parent"),
                children=nd.get("children", []),
                depends_on=nd.get("depends_on", []),
                source_file=nd.get("source_file"),
                source_line=nd.get("source_line"),
                test_commands=[
                    TestCommand.from_dict(tc)
                    for tc in nd.get("test_commands", [])
                ],
            )
        return tree
