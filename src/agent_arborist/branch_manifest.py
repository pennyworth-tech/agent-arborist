"""Branch manifest for deterministic branch naming.

The manifest is generated at DAG build time and contains pre-computed branch names
for all tasks. This ensures deterministic, reproducible branch naming based on the
source branch at the time of DAG generation.
"""

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

from agent_arborist.task_state import TaskTree, TaskNode


@dataclass
class TaskBranchInfo:
    """Branch information for a single task."""

    task_id: str
    branch: str
    parent_branch: str
    parent_task: str | None
    children: list[str] = field(default_factory=list)


@dataclass
class BranchManifest:
    """Complete branch manifest for a DAG.

    Contains pre-computed branch names for the base branch and all tasks.
    """

    source_branch: str  # Branch when dag build was run
    base_branch: str  # source_branch + "_a"
    spec_id: str
    created_at: str
    tasks: dict[str, TaskBranchInfo] = field(default_factory=dict)

    def get_task(self, task_id: str) -> TaskBranchInfo | None:
        """Get branch info for a task."""
        return self.tasks.get(task_id)


def generate_manifest(
    spec_id: str,
    task_tree: TaskTree,
    source_branch: str,
) -> BranchManifest:
    """Generate branch manifest from task tree.

    Branch naming scheme:
    - Base branch: <source_branch>_a
    - Root tasks: <source_branch>_a_T001
    - Child tasks: <source_branch>_a_T001_T004

    Args:
        spec_id: The spec identifier
        task_tree: Task hierarchy from task_state
        source_branch: Current git branch when dag build is run

    Returns:
        BranchManifest with all pre-computed branch names
    """
    base_branch = f"{source_branch}_a"

    manifest = BranchManifest(
        source_branch=source_branch,
        base_branch=base_branch,
        spec_id=spec_id,
        created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )

    # Process tasks in topological order so parent branches are computed first
    # Build a simple topological order: roots first, then children
    processed: dict[str, TaskBranchInfo] = {}
    remaining = dict(task_tree.tasks)

    while remaining:
        # Find tasks whose parent (if any) is already processed
        ready = [
            tid for tid, task in remaining.items()
            if task.parent_id is None or task.parent_id in processed
        ]

        if not ready:
            # Circular dependency or missing parent - just process remaining
            ready = list(remaining.keys())

        for task_id in ready:
            task = remaining.pop(task_id)

            if task.parent_id:
                # Child task: parent_branch + _task_id
                parent_info = processed[task.parent_id]
                parent_branch = parent_info.branch
                branch = f"{parent_branch}_{task_id}"
            else:
                # Root task: base_T001
                branch = f"{base_branch}_{task_id}"
                parent_branch = base_branch

            processed[task_id] = TaskBranchInfo(
                task_id=task_id,
                branch=branch,
                parent_branch=parent_branch,
                parent_task=task.parent_id,
                children=list(task.children),
            )

    manifest.tasks = processed
    return manifest


def save_manifest(manifest: BranchManifest, manifest_path: Path) -> None:
    """Save manifest to JSON file."""
    data = {
        "source_branch": manifest.source_branch,
        "base_branch": manifest.base_branch,
        "spec_id": manifest.spec_id,
        "created_at": manifest.created_at,
        "tasks": {
            task_id: asdict(info)
            for task_id, info in manifest.tasks.items()
        },
    }

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(data, indent=2))


def load_manifest(manifest_path: Path) -> BranchManifest:
    """Load manifest from JSON file.

    Raises:
        FileNotFoundError: If manifest file doesn't exist
        ValueError: If manifest is invalid
    """
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    data = json.loads(manifest_path.read_text())

    manifest = BranchManifest(
        source_branch=data["source_branch"],
        base_branch=data["base_branch"],
        spec_id=data["spec_id"],
        created_at=data["created_at"],
    )

    for task_id, info in data.get("tasks", {}).items():
        manifest.tasks[task_id] = TaskBranchInfo(
            task_id=info["task_id"],
            branch=info["branch"],
            parent_branch=info["parent_branch"],
            parent_task=info.get("parent_task"),
            children=info.get("children", []),
        )

    return manifest


def get_manifest_path_from_env() -> Path | None:
    """Get manifest path from ARBORIST_MANIFEST environment variable."""
    manifest_path = os.environ.get("ARBORIST_MANIFEST")
    if manifest_path:
        return Path(manifest_path)
    return None


def load_manifest_from_env() -> BranchManifest:
    """Load manifest from path specified in ARBORIST_MANIFEST env var.

    Raises:
        ValueError: If ARBORIST_MANIFEST is not set
        FileNotFoundError: If manifest file doesn't exist
    """
    manifest_path = get_manifest_path_from_env()
    if not manifest_path:
        raise ValueError("ARBORIST_MANIFEST environment variable not set")

    return load_manifest(manifest_path)


def topological_sort(tasks: dict[str, TaskBranchInfo]) -> list[str]:
    """Sort tasks in topological order (parents before children).

    This ensures branches are created in the right order - parent branches
    must exist before child branches can be created from them.

    Args:
        tasks: Dict of task_id -> TaskBranchInfo

    Returns:
        List of task IDs in topological order
    """
    # Build adjacency list (parent -> children)
    children_of: dict[str, list[str]] = {tid: [] for tid in tasks}
    for task_id, info in tasks.items():
        if info.parent_task and info.parent_task in children_of:
            children_of[info.parent_task].append(task_id)

    # Find root tasks (no parent)
    roots = [tid for tid, info in tasks.items() if info.parent_task is None]

    # BFS to get topological order
    result = []
    queue = list(roots)

    while queue:
        task_id = queue.pop(0)
        result.append(task_id)
        queue.extend(children_of.get(task_id, []))

    return result
