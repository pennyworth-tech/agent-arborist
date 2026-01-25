"""Task state management for tracking task hierarchy and execution status."""

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Literal

from agent_arborist.home import get_arborist_home
from agent_arborist.task_spec import parse_task_spec, TaskSpec


TaskStatus = Literal["pending", "running", "complete", "failed"]


@dataclass
class TaskNode:
    """A task in the hierarchy with its state."""

    task_id: str
    description: str
    status: TaskStatus = "pending"
    parent_id: str | None = None
    children: list[str] = field(default_factory=list)
    branch: str | None = None
    worktree: str | None = None
    error: str | None = None


@dataclass
class TaskTree:
    """Complete task hierarchy for a spec."""

    spec_id: str
    tasks: dict[str, TaskNode] = field(default_factory=dict)
    root_tasks: list[str] = field(default_factory=list)

    def get_task(self, task_id: str) -> TaskNode | None:
        """Get a task by ID."""
        return self.tasks.get(task_id)

    def get_parent(self, task_id: str) -> TaskNode | None:
        """Get parent task."""
        task = self.tasks.get(task_id)
        if task and task.parent_id:
            return self.tasks.get(task.parent_id)
        return None

    def get_children(self, task_id: str) -> list[TaskNode]:
        """Get child tasks."""
        task = self.tasks.get(task_id)
        if task:
            return [self.tasks[cid] for cid in task.children if cid in self.tasks]
        return []

    def is_leaf(self, task_id: str) -> bool:
        """Check if task has no children."""
        task = self.tasks.get(task_id)
        return task is not None and len(task.children) == 0

    def are_children_complete(self, task_id: str) -> bool:
        """Check if all children are complete."""
        children = self.get_children(task_id)
        return all(c.status == "complete" for c in children)

    def get_pending_tasks(self) -> list[TaskNode]:
        """Get all tasks that are pending."""
        return [t for t in self.tasks.values() if t.status == "pending"]

    def get_ready_tasks(self) -> list[TaskNode]:
        """Get tasks that are ready to run (pending with all deps complete)."""
        ready = []
        for task in self.tasks.values():
            if task.status != "pending":
                continue
            # Check if parent is set up (or no parent)
            if task.parent_id:
                parent = self.tasks.get(task.parent_id)
                if parent and parent.status not in ("running", "complete"):
                    continue
            ready.append(task)
        return ready


def get_state_path(spec_id: str) -> Path:
    """Get path to state file for a spec."""
    arborist_home = get_arborist_home()
    state_dir = arborist_home / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / f"{spec_id}.json"


def load_task_tree(spec_id: str) -> TaskTree | None:
    """Load task tree from state file."""
    state_path = get_state_path(spec_id)
    if not state_path.exists():
        return None

    data = json.loads(state_path.read_text())
    tree = TaskTree(spec_id=data["spec_id"], root_tasks=data.get("root_tasks", []))

    for task_id, task_data in data.get("tasks", {}).items():
        tree.tasks[task_id] = TaskNode(
            task_id=task_data["task_id"],
            description=task_data["description"],
            status=task_data.get("status", "pending"),
            parent_id=task_data.get("parent_id"),
            children=task_data.get("children", []),
            branch=task_data.get("branch"),
            worktree=task_data.get("worktree"),
            error=task_data.get("error"),
        )

    return tree


def save_task_tree(tree: TaskTree) -> None:
    """Save task tree to state file."""
    state_path = get_state_path(tree.spec_id)

    data = {
        "spec_id": tree.spec_id,
        "root_tasks": tree.root_tasks,
        "tasks": {tid: asdict(task) for tid, task in tree.tasks.items()},
    }

    state_path.write_text(json.dumps(data, indent=2))


def build_task_tree_from_spec(spec_id: str, spec_path: Path) -> TaskTree:
    """Build task tree from a task spec file.

    This parses the spec and infers parent-child relationships from dependencies.
    Tasks that depend on another task become children of that task.
    """
    spec = parse_task_spec(spec_path)
    tree = TaskTree(spec_id=spec_id)

    # First pass: create all task nodes
    for task in spec.tasks:
        tree.tasks[task.id] = TaskNode(
            task_id=task.id,
            description=task.description,
        )

    # Second pass: build hierarchy from dependencies
    # A task's parent is its first dependency (if any)
    for task_id, deps in spec.dependencies.items():
        if deps and task_id in tree.tasks:
            parent_id = deps[0]  # First dependency is the parent
            if parent_id in tree.tasks:
                tree.tasks[task_id].parent_id = parent_id
                if task_id not in tree.tasks[parent_id].children:
                    tree.tasks[parent_id].children.append(task_id)

    # Find root tasks (no parent)
    tree.root_tasks = [
        tid for tid, task in tree.tasks.items()
        if task.parent_id is None
    ]

    return tree


def build_task_tree_from_yaml(spec_id: str, yaml_content: str) -> TaskTree:
    """Build task tree from generated DAG YAML.

    Extracts task IDs and parent-child relationships from the multi-document
    YAML that was generated by AI or the deterministic builder.

    This is the preferred method as it ensures the manifest matches
    what was actually generated in the DAG.
    """
    import yaml
    import re

    tree = TaskTree(spec_id=spec_id)
    documents = list(yaml.safe_load_all(yaml_content))

    if not documents:
        return tree

    # First document is root DAG, rest are subdags (one per task)
    root_dag = documents[0]
    subdags = documents[1:] if len(documents) > 1 else []

    # Extract task IDs from subdags - each subdag name is a task ID
    task_ids = set()
    subdag_calls: dict[str, list[str]] = {}  # task_id -> list of child task_ids it calls

    for subdag in subdags:
        task_id = subdag.get("name", "")
        if not task_id or not re.match(r"T\d+", task_id):
            continue

        task_ids.add(task_id)

        # Find what other tasks this subdag calls
        calls = []
        for step in subdag.get("steps", []):
            call_target = step.get("call")
            if call_target and re.match(r"T\d+", call_target):
                calls.append(call_target)
        subdag_calls[task_id] = calls

    # Also check root dag for direct task calls (flat structure)
    root_calls = []
    for step in root_dag.get("steps", []):
        call_target = step.get("call")
        if call_target and re.match(r"T\d+", call_target):
            task_ids.add(call_target)
            root_calls.append(call_target)

    # Create task nodes
    for task_id in sorted(task_ids):
        tree.tasks[task_id] = TaskNode(
            task_id=task_id,
            description=task_id,  # We don't have description from YAML
        )

    # Build parent-child relationships from calls
    # If task A calls task B, then B is a child of A
    for parent_id, children in subdag_calls.items():
        if parent_id not in tree.tasks:
            continue
        for child_id in children:
            if child_id in tree.tasks:
                tree.tasks[child_id].parent_id = parent_id
                if child_id not in tree.tasks[parent_id].children:
                    tree.tasks[parent_id].children.append(child_id)

    # Find root tasks (no parent, or called directly from root dag)
    tree.root_tasks = [
        tid for tid, task in tree.tasks.items()
        if task.parent_id is None
    ]

    return tree


def update_task_status(
    spec_id: str,
    task_id: str,
    status: TaskStatus,
    branch: str | None = None,
    worktree: str | None = None,
    error: str | None = None,
) -> TaskTree | None:
    """Update a task's status and save."""
    tree = load_task_tree(spec_id)
    if not tree:
        return None

    task = tree.get_task(task_id)
    if not task:
        return None

    task.status = status
    if branch is not None:
        task.branch = branch
    if worktree is not None:
        task.worktree = worktree
    if error is not None:
        task.error = error

    save_task_tree(tree)
    return tree


def init_task_tree(spec_id: str, spec_path: Path) -> TaskTree:
    """Initialize task tree from spec if not exists, or load existing."""
    existing = load_task_tree(spec_id)
    if existing:
        return existing

    tree = build_task_tree_from_spec(spec_id, spec_path)
    save_task_tree(tree)
    return tree


def get_task_status_summary(tree: TaskTree) -> dict:
    """Get summary of task statuses."""
    summary = {
        "total": len(tree.tasks),
        "pending": 0,
        "running": 0,
        "complete": 0,
        "failed": 0,
    }

    for task in tree.tasks.values():
        summary[task.status] = summary.get(task.status, 0) + 1

    return summary
