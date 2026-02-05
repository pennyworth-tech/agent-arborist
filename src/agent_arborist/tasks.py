"""Jujutsu operations for task-based workflow.

This module provides Jujutsu (jj) operations as an alternative to Git for
Agent Arborist's parallel task execution. Jujutsu offers:

- Working copy as commit: No staging area, changes auto-tracked
- Automatic rebasing: Fix parent task, children auto-incorporate
- Conflicts as first-class citizens: Work continues, resolution deferred
- Operation log & undo: Full recovery from any state
- Revsets: Dynamic queries replace static manifests

Key concepts:
- Change ID: Stable identifier for a change (unlike commit SHA which changes on amend)
- Workspace: Separate working copy for parallel execution (like git worktree)
- Squash: Merge child's changes into parent (atomic operation)
"""

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from agent_arborist.home import get_arborist_home, get_git_root


# Type aliases
ChangeStatus = Literal["pending", "running", "done", "conflict", "failed"]


class JJError(Exception):
    """Base exception for Jujutsu operations."""
    pass


class JJNotInstalledError(JJError):
    """Raised when jj is not installed."""
    pass


class JJNotColocatedError(JJError):
    """Raised when repo is not colocated (jj + git)."""
    pass


class JJConflictError(JJError):
    """Raised when a change has unresolved conflicts."""
    pass


@dataclass
class JJResult:
    """Result from a jj operation."""
    success: bool
    message: str
    stdout: str = ""
    stderr: str = ""
    error: str | None = None


@dataclass
class ChangeInfo:
    """Information about a Jujutsu change."""
    change_id: str
    commit_id: str
    description: str
    author: str
    is_empty: bool
    has_conflict: bool
    parent_ids: list[str] = field(default_factory=list)


@dataclass
class TaskChange:
    """A Jujutsu change representing a task."""
    change_id: str
    task_id: str
    spec_id: str
    parent_change: str | None
    status: ChangeStatus = "pending"
    has_conflict: bool = False
    workspace_path: Path | None = None


def is_jj_installed() -> bool:
    """Check if jj is installed and accessible."""
    try:
        result = subprocess.run(
            ["jj", "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def is_jj_repo(cwd: Path | None = None) -> bool:
    """Check if current directory is a jj repository."""
    try:
        result = run_jj("root", cwd=cwd, check=False)
        return result.returncode == 0
    except JJNotInstalledError:
        return False


def is_colocated(cwd: Path | None = None) -> bool:
    """Check if repository is colocated (jj + git).

    Colocated repos have both .jj and .git directories.
    """
    root = cwd or get_git_root()
    if root is None:
        return False
    return (root / ".jj").exists() and (root / ".git").exists()


def run_jj(
    *args: str,
    cwd: Path | None = None,
    check: bool = True,
    capture_output: bool = True,
) -> subprocess.CompletedProcess:
    """Run a jj command.

    Args:
        *args: Command arguments (e.g., "log", "-r", "@")
        cwd: Working directory
        check: Raise on non-zero exit
        capture_output: Capture stdout/stderr

    Returns:
        CompletedProcess with stdout/stderr

    Raises:
        JJNotInstalledError: If jj is not installed
        subprocess.CalledProcessError: If check=True and command fails
    """
    if not is_jj_installed():
        raise JJNotInstalledError("jj is not installed. Install with: brew install jj")

    cmd = ["jj", *args]
    try:
        return subprocess.run(
            cmd,
            cwd=cwd or get_git_root(),
            capture_output=capture_output,
            text=True,
            check=check,
        )
    except subprocess.CalledProcessError:
        raise


def get_change_id(revset: str = "@", cwd: Path | None = None) -> str:
    """Get change ID for a revset.

    Args:
        revset: Jujutsu revset expression (default: @ for working copy)
        cwd: Working directory

    Returns:
        Change ID string (e.g., "qpvuntsm")
    """
    result = run_jj(
        "log", "-r", revset,
        "--no-graph", "-T", "change_id",
        cwd=cwd,
    )
    return result.stdout.strip()


def get_commit_id(revset: str = "@", cwd: Path | None = None) -> str:
    """Get commit ID for a revset.

    Args:
        revset: Jujutsu revset expression
        cwd: Working directory

    Returns:
        Commit ID string (SHA)
    """
    result = run_jj(
        "log", "-r", revset,
        "--no-graph", "-T", "commit_id",
        cwd=cwd,
    )
    return result.stdout.strip()


def get_change_info(revset: str = "@", cwd: Path | None = None) -> ChangeInfo:
    """Get detailed information about a change.

    Args:
        revset: Jujutsu revset expression
        cwd: Working directory

    Returns:
        ChangeInfo with change details
    """
    # Use a template to get structured output
    template = (
        'change_id ++ "\\n" ++ '
        'commit_id ++ "\\n" ++ '
        'description.first_line() ++ "\\n" ++ '
        'author.email() ++ "\\n" ++ '
        'if(empty, "true", "false") ++ "\\n" ++ '
        'if(conflict, "true", "false")'
    )

    result = run_jj(
        "log", "-r", revset,
        "--no-graph", "-T", template,
        cwd=cwd,
    )

    lines = result.stdout.strip().split("\n")

    return ChangeInfo(
        change_id=lines[0] if len(lines) > 0 else "",
        commit_id=lines[1] if len(lines) > 1 else "",
        description=lines[2] if len(lines) > 2 else "",
        author=lines[3] if len(lines) > 3 else "",
        is_empty=lines[4] == "true" if len(lines) > 4 else False,
        has_conflict=lines[5] == "true" if len(lines) > 5 else False,
    )


def get_description(revset: str = "@", cwd: Path | None = None) -> str:
    """Get description of a change.

    Args:
        revset: Jujutsu revset expression
        cwd: Working directory

    Returns:
        Full description text
    """
    result = run_jj(
        "log", "-r", revset,
        "--no-graph", "-T", "description",
        cwd=cwd,
    )
    return result.stdout.strip()


def has_conflicts(revset: str = "@", cwd: Path | None = None) -> bool:
    """Check if a change has conflicts.

    Args:
        revset: Jujutsu revset expression
        cwd: Working directory

    Returns:
        True if change has unresolved conflicts
    """
    result = run_jj(
        "log", "-r", f"{revset} & conflicts()",
        "--no-graph", "-T", "change_id",
        cwd=cwd,
        check=False,
    )
    return bool(result.stdout.strip())


def get_conflicting_files(revset: str = "@", cwd: Path | None = None) -> list[str]:
    """Get list of files with conflicts in a change.

    Args:
        revset: Jujutsu revset expression
        cwd: Working directory

    Returns:
        List of file paths with conflicts
    """
    # First check if there are conflicts
    if not has_conflicts(revset, cwd):
        return []

    # Switch to the change and list conflicts
    result = run_jj("resolve", "--list", cwd=cwd, check=False)
    if result.returncode != 0:
        return []

    return [
        line.strip()
        for line in result.stdout.strip().split("\n")
        if line.strip()
    ]


# =============================================================================
# Change Creation & Management
# =============================================================================

def create_change(
    parent: str = "main",
    description: str = "",
    cwd: Path | None = None,
) -> str:
    """Create a new change from parent.

    Args:
        parent: Parent revset (change ID, bookmark, or "main")
        description: Change description
        cwd: Working directory

    Returns:
        New change ID
    """
    args = ["new", parent]
    if description:
        args.extend(["-m", description])

    run_jj(*args, cwd=cwd)
    return get_change_id(cwd=cwd)


def create_task_change(
    spec_id: str,
    task_id: str,
    parent_change: str | None = None,
    depends_on: list[str] | None = None,
    cwd: Path | None = None,
) -> str:
    """Create a new change for a task.

    Args:
        spec_id: Specification identifier
        task_id: Task identifier (e.g., "T001")
        parent_change: Parent change ID (or "main" if None)
        depends_on: List of peer task IDs this depends on (for description)
        cwd: Working directory

    Returns:
        New change ID

    Description format:
        spec:<spec_id>:<task_id> [deps:T001,T002]
    """
    parent = parent_change or "main"

    # Build description with optional dependencies
    deps_str = f" [deps:{','.join(depends_on)}]" if depends_on else ""
    description = f"spec:{spec_id}:{task_id}{deps_str}"

    return create_change(parent=parent, description=description, cwd=cwd)


def describe_change(
    description: str,
    revset: str = "@",
    cwd: Path | None = None,
) -> JJResult:
    """Update description of a change.

    Args:
        description: New description text
        revset: Change to describe (default: working copy)
        cwd: Working directory

    Returns:
        JJResult with operation status
    """
    result = run_jj(
        "describe", "-r", revset, "-m", description,
        cwd=cwd,
        check=False,
    )

    return JJResult(
        success=result.returncode == 0,
        message="Description updated" if result.returncode == 0 else "Failed to update",
        stdout=result.stdout,
        stderr=result.stderr,
        error=result.stderr if result.returncode != 0 else None,
    )


def edit_change(change_id: str, cwd: Path | None = None) -> JJResult:
    """Switch working copy to edit a change.

    Args:
        change_id: Change ID to edit
        cwd: Working directory

    Returns:
        JJResult with operation status
    """
    result = run_jj("edit", change_id, cwd=cwd, check=False)

    return JJResult(
        success=result.returncode == 0,
        message=f"Now editing {change_id}" if result.returncode == 0 else "Failed to edit",
        stdout=result.stdout,
        stderr=result.stderr,
        error=result.stderr if result.returncode != 0 else None,
    )


def abandon_change(change_id: str, cwd: Path | None = None) -> JJResult:
    """Abandon a change (delete it).

    Args:
        change_id: Change ID to abandon
        cwd: Working directory

    Returns:
        JJResult with operation status
    """
    result = run_jj("abandon", change_id, cwd=cwd, check=False)

    return JJResult(
        success=result.returncode == 0,
        message=f"Abandoned {change_id}" if result.returncode == 0 else "Failed to abandon",
        stdout=result.stdout,
        stderr=result.stderr,
        error=result.stderr if result.returncode != 0 else None,
    )


# =============================================================================
# Squash & Rebase Operations
# =============================================================================

def squash_into_parent(
    child_change: str,
    parent_change: str,
    cwd: Path | None = None,
) -> JJResult:
    """Squash a child change into its parent.

    This is the primary merge operation in jj - it moves all changes
    from the child into the parent atomically.

    Args:
        child_change: Change ID to squash from
        parent_change: Change ID to squash into
        cwd: Working directory

    Returns:
        JJResult with operation status
    """
    result = run_jj(
        "squash", "--from", child_change, "--into", parent_change,
        cwd=cwd,
        check=False,
    )

    success = result.returncode == 0

    # Check if parent now has conflicts
    conflicts = has_conflicts(parent_change, cwd) if success else False

    message = f"Squashed {child_change} into {parent_change}"
    if conflicts:
        message += " (conflicts detected)"

    return JJResult(
        success=success,
        message=message if success else "Squash failed",
        stdout=result.stdout,
        stderr=result.stderr,
        error=result.stderr if not success else None,
    )


def rebase_change(
    change: str,
    destination: str,
    cwd: Path | None = None,
) -> JJResult:
    """Rebase a change onto a new destination.

    This propagates changes from the destination into the change.
    Used to update a child task with parent's latest work.

    Args:
        change: Change ID to rebase
        destination: New parent change ID
        cwd: Working directory

    Returns:
        JJResult with operation status
    """
    result = run_jj(
        "rebase", "-r", change, "-d", destination,
        cwd=cwd,
        check=False,
    )

    success = result.returncode == 0 or "already" in result.stderr.lower()

    return JJResult(
        success=success,
        message=f"Rebased {change} onto {destination}" if success else "Rebase failed",
        stdout=result.stdout,
        stderr=result.stderr,
        error=result.stderr if not success else None,
    )


def rebase_descendants(
    change: str,
    destination: str,
    cwd: Path | None = None,
) -> JJResult:
    """Rebase a change and all its descendants onto a new destination.

    Args:
        change: Change ID (and descendants) to rebase
        destination: New parent change ID
        cwd: Working directory

    Returns:
        JJResult with operation status
    """
    result = run_jj(
        "rebase", "-s", change, "-d", destination,
        cwd=cwd,
        check=False,
    )

    success = result.returncode == 0

    return JJResult(
        success=success,
        message=f"Rebased {change} and descendants onto {destination}" if success else "Rebase failed",
        stdout=result.stdout,
        stderr=result.stderr,
        error=result.stderr if not success else None,
    )


# =============================================================================
# Workspace Management (for parallel execution)
# =============================================================================

def get_workspace_path(spec_id: str, task_id: str) -> Path:
    """Get workspace path for a task.

    Args:
        spec_id: Specification ID
        task_id: Task ID

    Returns:
        Path to workspace directory
    """
    arborist_home = get_arborist_home()
    return arborist_home / "workspaces" / spec_id / task_id


def list_workspaces(cwd: Path | None = None) -> list[str]:
    """List all jj workspaces.

    Args:
        cwd: Working directory

    Returns:
        List of workspace names
    """
    result = run_jj("workspace", "list", cwd=cwd, check=False)
    if result.returncode != 0:
        return []

    # Parse output: "name: /path/to/workspace"
    workspaces = []
    for line in result.stdout.strip().split("\n"):
        if ":" in line:
            name = line.split(":")[0].strip()
            workspaces.append(name)

    return workspaces


def workspace_exists(workspace_name: str, cwd: Path | None = None) -> bool:
    """Check if a workspace exists.

    Args:
        workspace_name: Name of workspace
        cwd: Working directory

    Returns:
        True if workspace exists
    """
    return workspace_name in list_workspaces(cwd)


def create_workspace(
    workspace_path: Path,
    workspace_name: str,
    cwd: Path | None = None,
) -> JJResult:
    """Create a new workspace for parallel task execution.

    Args:
        workspace_path: Path for the new workspace
        workspace_name: Name for the workspace
        cwd: Working directory

    Returns:
        JJResult with operation status
    """
    if workspace_exists(workspace_name, cwd):
        return JJResult(
            success=True,
            message=f"Workspace {workspace_name} already exists",
        )

    # Ensure parent directory exists
    workspace_path.parent.mkdir(parents=True, exist_ok=True)

    result = run_jj(
        "workspace", "add", str(workspace_path), "--name", workspace_name,
        cwd=cwd,
        check=False,
    )

    return JJResult(
        success=result.returncode == 0,
        message=f"Created workspace {workspace_name}" if result.returncode == 0 else "Failed",
        stdout=result.stdout,
        stderr=result.stderr,
        error=result.stderr if result.returncode != 0 else None,
    )


def forget_workspace(workspace_name: str, cwd: Path | None = None) -> JJResult:
    """Remove a workspace (forget it, don't delete files).

    Args:
        workspace_name: Name of workspace to forget
        cwd: Working directory

    Returns:
        JJResult with operation status
    """
    result = run_jj("workspace", "forget", workspace_name, cwd=cwd, check=False)

    return JJResult(
        success=result.returncode == 0,
        message=f"Forgot workspace {workspace_name}" if result.returncode == 0 else "Failed",
        stdout=result.stdout,
        stderr=result.stderr,
        error=result.stderr if result.returncode != 0 else None,
    )


def setup_task_workspace(
    task_id: str,
    change_id: str,
    parent_change: str,
    workspace_path: Path,
    cwd: Path | None = None,
) -> JJResult:
    """Setup a workspace for task execution.

    This:
    1. Creates workspace if needed
    2. Switches workspace to task's change
    3. Rebases onto parent to get latest work

    Args:
        task_id: Task identifier
        change_id: Task's change ID
        parent_change: Parent's change ID
        workspace_path: Path for workspace
        cwd: Working directory (git root)

    Returns:
        JJResult with operation status
    """
    workspace_name = f"ws-{task_id}"

    # Create workspace if needed
    if not workspace_exists(workspace_name, cwd):
        result = create_workspace(workspace_path, workspace_name, cwd)
        if not result.success:
            return result

    # Switch workspace to task's change
    result = run_jj(
        "edit", change_id,
        cwd=workspace_path,
        check=False,
    )

    if result.returncode != 0:
        return JJResult(
            success=False,
            message=f"Failed to edit {change_id} in workspace",
            stderr=result.stderr,
            error=result.stderr,
        )

    # Rebase onto parent to get any sibling work
    rebase_result = rebase_change(change_id, parent_change, workspace_path)

    # Check for conflicts after rebase
    conflicts = has_conflicts(change_id, workspace_path)

    message = f"Workspace ready at {workspace_path}"
    if conflicts:
        message += " (conflicts detected, may need resolution)"

    return JJResult(
        success=True,
        message=message,
    )


# =============================================================================
# Task Lifecycle
# =============================================================================

def complete_task(
    task_id: str,
    change_id: str,
    parent_change: str,
    cwd: Path | None = None,
) -> JJResult:
    """Mark task complete and squash into parent.

    This:
    1. Updates description to mark as [DONE]
    2. Squashes changes into parent

    Args:
        task_id: Task identifier
        change_id: Task's change ID
        parent_change: Parent's change ID
        cwd: Working directory

    Returns:
        JJResult with operation status
    """
    # Get current description and mark as done
    current_desc = get_description(change_id, cwd)
    if "[DONE]" not in current_desc:
        done_desc = current_desc.replace(f":{task_id}", f":{task_id} [DONE]")
        describe_change(done_desc, change_id, cwd)

    # Squash into parent
    return squash_into_parent(change_id, parent_change, cwd)


def sync_parent(
    parent_change: str,
    spec_id: str,
    cwd: Path | None = None,
) -> dict:
    """Sync parent after child completion.

    This:
    1. Checks for conflicts in parent
    2. Rebases pending children onto updated parent

    Args:
        parent_change: Parent's change ID
        spec_id: Specification ID (for querying children)
        cwd: Working directory

    Returns:
        Dict with sync status:
        - conflicts_found: bool
        - children_rebased: list[str]
        - needs_resolution: bool
    """
    result = {
        "conflicts_found": False,
        "children_rebased": [],
        "needs_resolution": False,
    }

    # Check for conflicts
    if has_conflicts(parent_change, cwd):
        result["conflicts_found"] = True
        result["needs_resolution"] = True

        # Mark for human review
        current_desc = get_description(parent_change, cwd)
        if "[NEEDS_RESOLUTION]" not in current_desc:
            describe_change(
                f"{current_desc} [NEEDS_RESOLUTION]",
                parent_change,
                cwd,
            )

    # Find and rebase pending children
    pending = find_pending_children(parent_change, cwd)

    for child_id in pending:
        rebase_result = rebase_change(child_id, parent_change, cwd)
        if rebase_result.success:
            result["children_rebased"].append(child_id)

    return result


def find_pending_children(parent_change: str, cwd: Path | None = None) -> list[str]:
    """Find pending children of a change.

    Uses revset to find children that:
    - Are direct children of parent
    - Are mutable (not published)
    - Don't have [DONE] in description

    Args:
        parent_change: Parent's change ID
        cwd: Working directory

    Returns:
        List of pending child change IDs
    """
    revset = f"children({parent_change}) & mutable() & ~description('[DONE]')"

    result = run_jj(
        "log", "-r", revset,
        "--no-graph", "-T", 'change_id ++ "\\n"',
        cwd=cwd,
        check=False,
    )

    if result.returncode != 0:
        return []

    return [
        cid.strip()
        for cid in result.stdout.strip().split("\n")
        if cid.strip()
    ]


# =============================================================================
# Query Functions (Revsets)
# =============================================================================

def find_tasks_by_spec(spec_id: str, cwd: Path | None = None) -> list[TaskChange]:
    """Find all task changes for a spec using revsets.

    Args:
        spec_id: Specification ID to search for
        cwd: Working directory

    Returns:
        List of TaskChange objects
    """
    # Query for all changes with spec description pattern
    revset = f'description("spec:{spec_id}:") & mutable()'

    # Template to get structured output
    template = 'change_id ++ "|" ++ description ++ "\\n"'

    result = run_jj(
        "log", "-r", revset,
        "--no-graph", "-T", template,
        cwd=cwd,
        check=False,
    )

    if result.returncode != 0:
        return []

    tasks = []
    for line in result.stdout.strip().split("\n"):
        if "|" not in line:
            continue

        change_id, desc = line.split("|", 1)
        change_id = change_id.strip()
        desc = desc.strip()

        # Parse task ID from description: "spec:SPEC:TASK [optional status]"
        parts = desc.split(":")
        if len(parts) < 3:
            continue

        task_id = parts[2].split()[0].split("[")[0]

        # Determine status from description
        status: ChangeStatus = "pending"
        if "[DONE]" in desc:
            status = "done"
        elif "[NEEDS_RESOLUTION]" in desc:
            status = "conflict"
        elif "[FAILED]" in desc:
            status = "failed"
        elif "[RUNNING]" in desc:
            status = "running"

        tasks.append(TaskChange(
            change_id=change_id,
            task_id=task_id,
            spec_id=spec_id,
            parent_change=None,  # Would need additional query
            status=status,
            has_conflict=has_conflicts(change_id, cwd),
        ))

    return tasks


def find_task_change(
    spec_id: str,
    task_id: str,
    cwd: Path | None = None,
) -> TaskChange | None:
    """Find a specific task's change.

    Args:
        spec_id: Specification ID
        task_id: Task ID
        cwd: Working directory

    Returns:
        TaskChange if found, None otherwise
    """
    revset = f'description("spec:{spec_id}:{task_id}") & mutable()'

    result = run_jj(
        "log", "-r", revset,
        "--no-graph", "-T", "change_id",
        cwd=cwd,
        check=False,
    )

    if result.returncode != 0 or not result.stdout.strip():
        return None

    change_id = result.stdout.strip().split("\n")[0]

    # Get full info
    desc = get_description(change_id, cwd)

    status: ChangeStatus = "pending"
    if "[DONE]" in desc:
        status = "done"
    elif "[NEEDS_RESOLUTION]" in desc:
        status = "conflict"
    elif "[FAILED]" in desc:
        status = "failed"
    elif "[RUNNING]" in desc:
        status = "running"

    return TaskChange(
        change_id=change_id,
        task_id=task_id,
        spec_id=spec_id,
        parent_change=None,
        status=status,
        has_conflict=has_conflicts(change_id, cwd),
    )


def get_task_status(spec_id: str, cwd: Path | None = None) -> dict:
    """Get status of all tasks in a spec.

    Args:
        spec_id: Specification ID
        cwd: Working directory

    Returns:
        Dict with status summary:
        - total: int
        - pending: int
        - running: int
        - done: int
        - conflict: int
        - failed: int
        - tasks: list[TaskChange]
    """
    tasks = find_tasks_by_spec(spec_id, cwd)

    status_counts = {
        "pending": 0,
        "running": 0,
        "done": 0,
        "conflict": 0,
        "failed": 0,
    }

    for task in tasks:
        if task.status in status_counts:
            status_counts[task.status] += 1

    return {
        "total": len(tasks),
        **status_counts,
        "tasks": tasks,
    }


# =============================================================================
# Operation Log & Recovery
# =============================================================================

def get_operation_log(limit: int = 10, cwd: Path | None = None) -> list[dict]:
    """Get recent operations from jj op log.

    Args:
        limit: Maximum operations to return
        cwd: Working directory

    Returns:
        List of operation dicts with id, description, time
    """
    template = 'self.id().short() ++ "|" ++ description ++ "\\n"'

    result = run_jj(
        "op", "log", "--no-graph", "-T", template, "-l", str(limit),
        cwd=cwd,
        check=False,
    )

    if result.returncode != 0:
        return []

    ops = []
    for line in result.stdout.strip().split("\n"):
        if "|" not in line:
            continue

        op_id, desc = line.split("|", 1)
        ops.append({
            "id": op_id.strip(),
            "description": desc.strip(),
        })

    return ops


def get_last_operation(cwd: Path | None = None) -> str | None:
    """Get ID of the last operation (for rollback).

    Args:
        cwd: Working directory

    Returns:
        Operation ID string, or None if no operations
    """
    ops = get_operation_log(limit=1, cwd=cwd)
    return ops[0]["id"] if ops else None


def undo_operation(cwd: Path | None = None) -> JJResult:
    """Undo the last operation.

    Args:
        cwd: Working directory

    Returns:
        JJResult with operation status
    """
    result = run_jj("undo", cwd=cwd, check=False)

    return JJResult(
        success=result.returncode == 0,
        message="Undid last operation" if result.returncode == 0 else "Undo failed",
        stdout=result.stdout,
        stderr=result.stderr,
        error=result.stderr if result.returncode != 0 else None,
    )


def restore_operation(op_id: str, cwd: Path | None = None) -> JJResult:
    """Restore to a previous operation state.

    Args:
        op_id: Operation ID to restore to
        cwd: Working directory

    Returns:
        JJResult with operation status
    """
    result = run_jj("op", "restore", op_id, cwd=cwd, check=False)

    return JJResult(
        success=result.returncode == 0,
        message=f"Restored to operation {op_id}" if result.returncode == 0 else "Restore failed",
        stdout=result.stdout,
        stderr=result.stderr,
        error=result.stderr if result.returncode != 0 else None,
    )


# =============================================================================
# Git Integration (colocated repos)
# =============================================================================

def git_export(cwd: Path | None = None) -> JJResult:
    """Export jj changes to git.

    In a colocated repo, this updates git refs to match jj state.

    Args:
        cwd: Working directory

    Returns:
        JJResult with operation status
    """
    result = run_jj("git", "export", cwd=cwd, check=False)

    return JJResult(
        success=result.returncode == 0,
        message="Exported to git" if result.returncode == 0 else "Export failed",
        stdout=result.stdout,
        stderr=result.stderr,
        error=result.stderr if result.returncode != 0 else None,
    )


def git_import(cwd: Path | None = None) -> JJResult:
    """Import git changes into jj.

    In a colocated repo, this updates jj to match git state.

    Args:
        cwd: Working directory

    Returns:
        JJResult with operation status
    """
    result = run_jj("git", "import", cwd=cwd, check=False)

    return JJResult(
        success=result.returncode == 0,
        message="Imported from git" if result.returncode == 0 else "Import failed",
        stdout=result.stdout,
        stderr=result.stderr,
        error=result.stderr if result.returncode != 0 else None,
    )


def create_bookmark(
    name: str,
    revset: str = "@",
    cwd: Path | None = None,
) -> JJResult:
    """Create a bookmark (jj's equivalent of git branch).

    Args:
        name: Bookmark name
        revset: Change to bookmark
        cwd: Working directory

    Returns:
        JJResult with operation status
    """
    result = run_jj(
        "bookmark", "create", name, "-r", revset,
        cwd=cwd,
        check=False,
    )

    return JJResult(
        success=result.returncode == 0,
        message=f"Created bookmark {name}" if result.returncode == 0 else "Failed",
        stdout=result.stdout,
        stderr=result.stderr,
        error=result.stderr if result.returncode != 0 else None,
    )


def push_bookmark(
    name: str,
    remote: str = "origin",
    cwd: Path | None = None,
) -> JJResult:
    """Push a bookmark to remote.

    Args:
        name: Bookmark name
        remote: Remote name (default: origin)
        cwd: Working directory

    Returns:
        JJResult with operation status
    """
    result = run_jj(
        "git", "push", "-b", name, "--remote", remote,
        cwd=cwd,
        check=False,
    )

    return JJResult(
        success=result.returncode == 0,
        message=f"Pushed {name} to {remote}" if result.returncode == 0 else "Push failed",
        stdout=result.stdout,
        stderr=result.stderr,
        error=result.stderr if result.returncode != 0 else None,
    )


# =============================================================================
# Initialization
# =============================================================================

def init_colocated(cwd: Path | None = None) -> JJResult:
    """Initialize jj in colocated mode with existing git repo.

    This allows using both git and jj commands on the same repository.

    Args:
        cwd: Working directory (must be git repo root)

    Returns:
        JJResult with operation status
    """
    git_root = cwd or get_git_root()

    # Check if already colocated
    if is_colocated(git_root):
        return JJResult(
            success=True,
            message="Repository already colocated",
        )

    # Check if .jj exists but no .git
    if (git_root / ".jj").exists():
        return JJResult(
            success=False,
            message="Repository has .jj but no .git - not a colocated repo",
            error="Use jj git init --colocate to convert",
        )

    # Initialize jj with colocate
    result = run_jj(
        "git", "init", "--colocate",
        cwd=git_root,
        check=False,
    )

    return JJResult(
        success=result.returncode == 0,
        message="Initialized colocated repository" if result.returncode == 0 else "Init failed",
        stdout=result.stdout,
        stderr=result.stderr,
        error=result.stderr if result.returncode != 0 else None,
    )


# =============================================================================
# Utility Functions (project-agnostic)
# =============================================================================

def detect_test_command(workspace: Path) -> str | None:
    """Auto-detect test command based on project files.

    Args:
        workspace: Path to workspace/worktree directory

    Returns:
        Test command string, or None if no test command detected
    """
    if (workspace / "pyproject.toml").exists() or (workspace / "pytest.ini").exists():
        return "pytest"
    if (workspace / "package.json").exists():
        return "npm test"
    if (workspace / "Makefile").exists():
        # Check if Makefile has a test target
        makefile_content = (workspace / "Makefile").read_text()
        if "test:" in makefile_content:
            return "make test"
    if (workspace / "Cargo.toml").exists():
        return "cargo test"
    if (workspace / "go.mod").exists():
        return "go test ./..."
    return None


def run_tests(
    workspace: Path,
    test_cmd: str | None = None,
    container_cmd_prefix: list[str] | None = None,
) -> JJResult:
    """Run tests in the workspace.

    Args:
        workspace: Path to workspace
        test_cmd: Test command to run (auto-detected if None)
        container_cmd_prefix: Optional devcontainer exec prefix for running in container

    Returns:
        JJResult with success status and output
    """
    cmd = test_cmd or detect_test_command(workspace)

    if not cmd:
        return JJResult(success=True, message="No test command detected, skipping tests")

    try:
        # Handle container wrapping
        if container_cmd_prefix:
            # Build full command for container execution
            # Need to join cmd with bash -c if it's a shell command
            full_cmd = container_cmd_prefix + ["bash", "-c", cmd]
            result = subprocess.run(
                full_cmd,
                capture_output=True,
                text=True,
            )
        else:
            # Run directly on host
            result = subprocess.run(
                cmd,
                shell=True,
                cwd=workspace,
                capture_output=True,
                text=True,
            )

        if result.returncode == 0:
            return JJResult(success=True, message="Tests passed", stdout=result.stdout, stderr=result.stderr)

        return JJResult(
            success=False,
            message="Tests failed",
            stdout=result.stdout,
            stderr=result.stderr,
            error=result.stdout + result.stderr,
        )
    except Exception as e:
        return JJResult(success=False, message="Failed to run tests", error=str(e))
