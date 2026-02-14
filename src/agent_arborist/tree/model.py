"""Task tree model - dataclasses for the task hierarchy."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass
class TaskNode:
    id: str
    name: str
    description: str = ""
    parent: str | None = None
    children: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)

    @property
    def is_leaf(self) -> bool:
        return len(self.children) == 0


@dataclass
class TaskTree:
    spec_id: str
    namespace: str = "feature"
    nodes: dict[str, TaskNode] = field(default_factory=dict)
    root_ids: list[str] = field(default_factory=list)
    execution_order: list[str] = field(default_factory=list)

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

    def branch_name(self, node_id: str) -> str:
        """Get the git branch name for a node.

        Phase nodes own branches: feature/calc/phase1
        Leaf tasks inherit their parent's branch.
        """
        node = self.nodes[node_id]
        if node.is_leaf and node.parent:
            # Leaf inherits parent's branch
            return self.branch_name(node.parent)
        # Phase node gets its own branch
        return f"{self.namespace}/{self.spec_id}/{node_id}"

    def compute_execution_order(self) -> list[str]:
        """Compute topological execution order using Kahn's algorithm.

        Only includes leaf tasks (actual work items).
        """
        leaves = {n.id for n in self.leaves()}

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
        queue = deque(sorted(nid for nid, deg in in_degree.items() if deg == 0))
        order: list[str] = []

        while queue:
            nid = queue.popleft()
            order.append(nid)
            for dep in sorted(dependents.get(nid, [])):
                in_degree[dep] -= 1
                if in_degree[dep] == 0:
                    queue.append(dep)

        self.execution_order = order
        return order

    def to_dict(self) -> dict:
        return {
            "spec_id": self.spec_id,
            "namespace": self.namespace,
            "nodes": {
                nid: {
                    "id": n.id,
                    "name": n.name,
                    "description": n.description,
                    "parent": n.parent,
                    "children": n.children,
                    "depends_on": n.depends_on,
                    "is_leaf": n.is_leaf,
                }
                for nid, n in self.nodes.items()
            },
            "root_ids": self.root_ids,
            "execution_order": self.execution_order,
        }

    @classmethod
    def from_dict(cls, data: dict) -> TaskTree:
        tree = cls(
            spec_id=data["spec_id"],
            namespace=data.get("namespace", "feature"),
            root_ids=data.get("root_ids", []),
            execution_order=data.get("execution_order", []),
        )
        for nid, nd in data.get("nodes", {}).items():
            tree.nodes[nid] = TaskNode(
                id=nd["id"],
                name=nd["name"],
                description=nd.get("description", ""),
                parent=nd.get("parent"),
                children=nd.get("children", []),
                depends_on=nd.get("depends_on", []),
            )
        return tree
