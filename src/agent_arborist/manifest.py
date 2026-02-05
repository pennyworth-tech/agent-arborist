"""Task manifest for tracking changes in Jujutsu (jj).

The manifest is generated at DAG build time and contains pre-computed change IDs
for all tasks.

Key features:
- Change IDs are stable (don't change on amend, unlike commit SHAs)
- No branch naming scheme needed - changes ARE the identifiers
- Hierarchy is encoded in the change DAG, not branch names
- Revsets can dynamically query task state
"""

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

from agent_arborist.home import get_arborist_home
from agent_arborist.task_state import TaskTree, TaskNode


@dataclass
class TaskChangeInfo:
    """Change information for a single task."""

    task_id: str
    change_id: str
    parent_change: str  # Parent task's change ID (or "main")
    parent_task: str | None  # Parent task ID (None for root tasks)
    children: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)  # Peer dependencies


@dataclass
class ChangeManifest:
    """Complete change manifest for a DAG.

    Contains pre-computed change IDs for all tasks in a spec.
    """

    spec_id: str
    base_change: str  # Change ID for integration point (usually "main" bookmark)
    source_rev: str  # Revset used as base (e.g., "main", "trunk()")
    created_at: str
    vcs: str = "jj"  # Version control system identifier
    tasks: dict[str, TaskChangeInfo] = field(default_factory=dict)

    def get_task(self, task_id: str) -> TaskChangeInfo | None:
        """Get change info for a task."""
        return self.tasks.get(task_id)

    def get_change_id(self, task_id: str) -> str | None:
        """Get change ID for a task."""
        task = self.tasks.get(task_id)
        return task.change_id if task else None

    def get_parent_change(self, task_id: str) -> str | None:
        """Get parent's change ID for a task."""
        task = self.tasks.get(task_id)
        return task.parent_change if task else None


def generate_manifest(
    spec_id: str,
    task_tree: TaskTree,
    source_rev: str = "main",
    create_changes: bool = True,
    cwd: Path | None = None,
) -> ChangeManifest:
    """Generate change manifest from task tree.

    This creates jj changes for each task in topological order,
    recording their change IDs in the manifest.

    Args:
        spec_id: The spec identifier
        task_tree: Task hierarchy from task_state
        source_rev: Base revset (e.g., "main", "trunk()")
        create_changes: If True, actually create jj changes. If False, generate
                        placeholder IDs (for testing or dry-run).
        cwd: Working directory for jj commands

    Returns:
        ChangeManifest with all change IDs populated
    """
    from agent_arborist.tasks import (
        create_task_change,
        get_change_id,
        is_jj_repo,
    )

    manifest = ChangeManifest(
        spec_id=spec_id,
        base_change=source_rev,
        source_rev=source_rev,
        created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )

    # If creating real changes, verify we're in a jj repo
    if create_changes and not is_jj_repo(cwd):
        raise ValueError("Not in a jj repository. Run 'jj git init --colocate' first.")

    # If creating changes, get the actual change ID for base
    if create_changes:
        manifest.base_change = get_change_id(source_rev, cwd)

    # Process tasks in topological order so parents are created first
    processed: dict[str, TaskChangeInfo] = {}
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
                # Child task: parent is the parent task's change
                parent_info = processed[task.parent_id]
                parent_change = parent_info.change_id
            else:
                # Root task: parent is the base change
                parent_change = manifest.base_change

            # Create the change (or generate placeholder)
            if create_changes:
                change_id = create_task_change(
                    spec_id=spec_id,
                    task_id=task_id,
                    parent_change=parent_change,
                    cwd=cwd,
                )
            else:
                # Generate deterministic placeholder for testing
                change_id = f"change_{spec_id}_{task_id}".lower().replace("-", "_")

            processed[task_id] = TaskChangeInfo(
                task_id=task_id,
                change_id=change_id,
                parent_change=parent_change,
                parent_task=task.parent_id,
                children=list(task.children),
            )

    manifest.tasks = processed
    return manifest


def save_manifest(manifest: ChangeManifest, manifest_path: Path) -> None:
    """Save manifest to JSON file."""
    data = {
        "spec_id": manifest.spec_id,
        "base_change": manifest.base_change,
        "source_rev": manifest.source_rev,
        "created_at": manifest.created_at,
        "vcs": manifest.vcs,
        "tasks": {
            task_id: asdict(info)
            for task_id, info in manifest.tasks.items()
        },
    }

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(data, indent=2))


def load_manifest(manifest_path: Path) -> ChangeManifest:
    """Load manifest from JSON file.

    Raises:
        FileNotFoundError: If manifest file doesn't exist
        ValueError: If manifest is invalid or not a jj manifest
    """
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    data = json.loads(manifest_path.read_text())

    # Check if this is a jj manifest
    vcs = data.get("vcs", "git")
    if vcs != "jj":
        raise ValueError(f"Not a jj manifest (vcs={vcs}). Use branch_manifest for git.")

    manifest = ChangeManifest(
        spec_id=data["spec_id"],
        base_change=data["base_change"],
        source_rev=data.get("source_rev", data["base_change"]),
        created_at=data["created_at"],
        vcs=vcs,
    )

    for task_id, info in data.get("tasks", {}).items():
        manifest.tasks[task_id] = TaskChangeInfo(
            task_id=info["task_id"],
            change_id=info["change_id"],
            parent_change=info["parent_change"],
            parent_task=info.get("parent_task"),
            children=info.get("children", []),
            depends_on=info.get("depends_on", []),
        )

    return manifest


def get_manifest_path(spec_id: str, arborist_home: Path | None = None) -> Path:
    """Get path to manifest file for a spec.

    Args:
        spec_id: Specification ID
        arborist_home: Override for arborist home directory

    Returns:
        Path to manifest JSON file
    """
    home = arborist_home or get_arborist_home()
    return home / "dagu" / "dags" / f"{spec_id}.json"


def get_manifest_path_from_env() -> Path | None:
    """Get manifest path from ARBORIST_MANIFEST environment variable."""
    manifest_path = os.environ.get("ARBORIST_MANIFEST")
    if manifest_path:
        return Path(manifest_path)
    return None


def load_manifest_from_env() -> ChangeManifest:
    """Load manifest from path specified in ARBORIST_MANIFEST env var.

    Raises:
        ValueError: If ARBORIST_MANIFEST is not set
        FileNotFoundError: If manifest file doesn't exist
    """
    manifest_path = get_manifest_path_from_env()
    if not manifest_path:
        raise ValueError("ARBORIST_MANIFEST environment variable not set")

    return load_manifest(manifest_path)


def find_manifest_path(spec_id: str, git_root: Path | None = None) -> Path | None:
    """Find manifest file using discovery strategy.

    Args:
        spec_id: Specification ID for the DAG
        git_root: Git repository root (optional, will auto-detect if not provided)

    Returns:
        Path to manifest file, or None if not found

    Search order:
    1. {git_root}/.arborist/dagu/dags/{spec_id}.json
    2. {git_root}/.arborist/{spec_id}.json
    3. {git_root}/specs/{spec_id}/manifest.json
    """
    if git_root is None:
        try:
            from agent_arborist.home import get_git_root
            git_root = get_git_root()
        except Exception:
            return None

    if git_root is None:
        return None

    # Search in order
    search_paths = [
        git_root / ".arborist" / "dagu" / "dags" / f"{spec_id}.json",
        git_root / ".arborist" / f"{spec_id}.json",
        git_root / "specs" / spec_id / "manifest.json",
    ]

    for path in search_paths:
        if path.exists():
            return path

    return None


def topological_sort(tasks: dict[str, TaskChangeInfo]) -> list[str]:
    """Sort tasks in topological order (parents before children).

    This ensures changes are created in the right order - parent changes
    must exist before child changes can be created from them.

    Args:
        tasks: Dict of task_id -> TaskChangeInfo

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


def create_all_changes_from_manifest(
    manifest: ChangeManifest,
    cwd: Path | None = None,
) -> dict:
    """Verify all changes exist, creating any missing ones.

    This is a recovery/validation function that ensures all changes
    referenced in the manifest actually exist in the repository.

    Args:
        manifest: ChangeManifest with expected change IDs
        cwd: Working directory for jj commands

    Returns:
        Dict with:
        - verified: list of change IDs that exist
        - created: list of change IDs that were created
        - errors: list of errors encountered
    """
    from agent_arborist.tasks import (
        get_change_id,
        create_task_change,
        run_jj,
    )

    result = {
        "verified": [],
        "created": [],
        "errors": [],
    }

    # Process in topological order
    task_order = topological_sort(manifest.tasks)

    for task_id in task_order:
        task_info = manifest.tasks[task_id]

        # Check if change exists
        try:
            check = run_jj(
                "log", "-r", task_info.change_id,
                "--no-graph", "-T", "change_id",
                cwd=cwd,
                check=False,
            )

            if check.returncode == 0 and check.stdout.strip():
                result["verified"].append(task_info.change_id)
                continue

        except Exception as e:
            result["errors"].append(f"{task_id}: {e}")
            continue

        # Change doesn't exist, try to create it
        try:
            new_change_id = create_task_change(
                spec_id=manifest.spec_id,
                task_id=task_id,
                parent_change=task_info.parent_change,
                depends_on=task_info.depends_on if task_info.depends_on else None,
                cwd=cwd,
            )
            result["created"].append(new_change_id)

            # Update manifest with new change ID
            task_info.change_id = new_change_id

        except Exception as e:
            result["errors"].append(f"{task_id}: Failed to create - {e}")

    return result


def refresh_manifest_from_repo(
    spec_id: str,
    cwd: Path | None = None,
) -> ChangeManifest | None:
    """Rebuild manifest from repository state using revsets.

    This queries the repository to find all changes for a spec and
    rebuilds the manifest from the actual repository state.

    Args:
        spec_id: Specification ID
        cwd: Working directory for jj commands

    Returns:
        ChangeManifest rebuilt from repo, or None if no changes found
    """
    from agent_arborist.tasks import (
        find_tasks_by_spec,
        get_change_id,
        run_jj,
    )

    # Find all tasks for this spec
    tasks = find_tasks_by_spec(spec_id, cwd)

    if not tasks:
        return None

    # Try to determine base change (main or trunk)
    try:
        base_change = get_change_id("main", cwd)
    except Exception:
        try:
            base_change = get_change_id("trunk()", cwd)
        except Exception:
            base_change = "root()"

    manifest = ChangeManifest(
        spec_id=spec_id,
        base_change=base_change,
        source_rev="main",
        created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )

    # Build task info from discovered changes
    for task in tasks:
        # Try to find parent from ancestors
        parent_change = base_change
        parent_task = None

        # Query for parent
        parent_result = run_jj(
            "log", "-r", f"parents({task.change_id}) & description('spec:{spec_id}:')",
            "--no-graph", "-T", "change_id",
            cwd=cwd,
            check=False,
        )

        if parent_result.returncode == 0 and parent_result.stdout.strip():
            parent_change = parent_result.stdout.strip().split("\n")[0]
            # Find parent task ID
            for other_task in tasks:
                if other_task.change_id == parent_change:
                    parent_task = other_task.task_id
                    break

        manifest.tasks[task.task_id] = TaskChangeInfo(
            task_id=task.task_id,
            change_id=task.change_id,
            parent_change=parent_change,
            parent_task=parent_task,
            children=[],  # Will be filled in second pass
        )

    # Second pass: fill in children
    for task_id, info in manifest.tasks.items():
        if info.parent_task and info.parent_task in manifest.tasks:
            manifest.tasks[info.parent_task].children.append(task_id)

    return manifest


def is_jj_manifest(manifest_path: Path) -> bool:
    """Check if a manifest file is a jj manifest.

    Args:
        manifest_path: Path to manifest file

    Returns:
        True if this is a jj manifest, False otherwise
    """
    if not manifest_path.exists():
        return False

    try:
        data = json.loads(manifest_path.read_text())
        return data.get("vcs") == "jj"
    except Exception:
        return False


def detect_manifest_type(manifest_path: Path) -> str:
    """Detect the type of manifest file.

    Args:
        manifest_path: Path to manifest file

    Returns:
        "jj" for jj manifests, "git" for git manifests, "unknown" otherwise
    """
    if not manifest_path.exists():
        return "unknown"

    try:
        data = json.loads(manifest_path.read_text())

        # Check for jj manifest
        if data.get("vcs") == "jj":
            return "jj"

        # Check for git manifest (has source_branch and base_branch)
        if "source_branch" in data and "base_branch" in data:
            return "git"

        return "unknown"

    except Exception:
        return "unknown"

