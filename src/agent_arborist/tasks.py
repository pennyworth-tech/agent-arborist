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
import os
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


def get_changed_files(revset: str = "@", cwd: Path | None = None) -> list[str]:
    """Get list of files changed by a commit.

    Args:
        revset: Jujutsu revset expression
        cwd: Working directory

    Returns:
        List of file paths that were modified
    """
    result = run_jj(
        "diff", "-r", revset, "--summary",
        cwd=cwd,
        check=False,
    )
    if result.returncode != 0:
        return []

    files = []
    for line in result.stdout.strip().split("\n"):
        if line.strip():
            # Format is "M path/to/file" or "A path/to/file" etc.
            parts = line.split(maxsplit=1)
            if len(parts) == 2:
                files.append(parts[1])
    return files


@dataclass
class ChildTaskInfo:
    """Information about a completed child task."""
    task_id: str
    change_id: str
    description: str
    files_changed: list[str]


def get_child_task_info(
    change_id: str,
    cwd: Path | None = None,
) -> ChildTaskInfo:
    """Get detailed info about a child task change.

    Args:
        change_id: The jj change ID
        cwd: Working directory

    Returns:
        ChildTaskInfo with description and files changed
    """
    desc = get_description(change_id, cwd=cwd)
    files = get_changed_files(change_id, cwd=cwd)

    # Extract task_id from description (format: "spec_id:task_path [DONE]")
    task_id = ""
    if ":" in desc:
        parts = desc.split(":")
        if len(parts) >= 2:
            task_id = parts[-1].split()[0]  # Last part before any tags

    return ChildTaskInfo(
        task_id=task_id,
        change_id=change_id,
        description=desc,
        files_changed=files,
    )


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
    parent: str,
    description: str = "",
    cwd: Path | None = None,
) -> str:
    """Create a new change from parent.

    Args:
        parent: Parent revset (change ID or bookmark). Never use 'main'.
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


# =============================================================================
# Hierarchical Task Description Helpers
# =============================================================================

def build_task_description(spec_id: str, task_path: list[str]) -> str:
    """Build hierarchical task description.

    Args:
        spec_id: Specification identifier (e.g., "003-terraform-hello-world")
        task_path: List of task IDs forming the path (e.g., ["T1", "T2", "T6"])

    Returns:
        Hierarchical description: "003-terraform-hello-world:T1:T2:T6"
    """
    return f"{spec_id}:{':'.join(task_path)}"


def build_rich_description(
    spec_id: str,
    task_id: str,
    status: str = "DONE",
    commit_message: str | None = None,
    summary: str = "",
    files_changed: int = 0,
    test_command: str | None = None,
    test_passed: int | None = None,
    test_failed: int | None = None,
    test_total: int | None = None,
    runner: str = "",
    model: str | None = None,
    duration_seconds: float = 0.0,
    children_ids: list[str] | None = None,
    conflicts_resolved: list[tuple[str, str]] | None = None,
) -> str:
    """Build a rich multi-line description for a jj change.

    Args:
        spec_id: Specification identifier
        task_id: Task identifier (e.g., "T001" or "ROOT")
        status: Status marker (DONE, MERGE, RUNNING)
        commit_message: One-line commit message from AI
        summary: Longer summary of what was accomplished
        files_changed: Number of files modified
        test_command: Test command that was run
        test_passed: Number of tests passed
        test_failed: Number of tests failed
        test_total: Total number of tests
        runner: AI runner used (e.g., "opencode")
        model: Model used (e.g., "cerebras/zai-glm-4.7")
        duration_seconds: Execution duration
        children_ids: List of child task IDs that were merged
        conflicts_resolved: List of (filepath, resolution_note) tuples

    Returns:
        Multi-line description suitable for jj commit message
    """
    lines = []

    # First line: spec:task: commit_message
    first_line = f"{spec_id}:{task_id}"
    if commit_message:
        first_line += f": {commit_message}"
    lines.append(first_line)
    lines.append("")

    # Status marker
    lines.append(f"[{status}]")
    lines.append("")

    # Summary section (for leaf tasks)
    if summary and not children_ids:
        lines.append("## Summary")
        # Truncate and clean summary
        clean_summary = summary.strip()[:500]
        if clean_summary:
            lines.append(clean_summary)
        lines.append("")
        lines.append(f"Files changed: {files_changed}")
        lines.append("")

    # Merge work section (for parent tasks)
    if children_ids:
        if summary:
            lines.append("## Merge Work")
            clean_summary = summary.strip()[:500]
            if clean_summary:
                lines.append(clean_summary)
            lines.append("")

        # Children rolled up
        lines.append("## Children Rolled Up")
        lines.append(", ".join(children_ids))
        lines.append("")

    # Conflicts resolved
    if conflicts_resolved:
        lines.append("## Conflicts Resolved")
        for filepath, note in conflicts_resolved:
            lines.append(f"- {filepath}: {note}")
        lines.append("")

    # Tests section
    if test_command:
        lines.append("## Tests")
        lines.append(f"Command: {test_command}")
        if test_total is not None:
            passed = test_passed or 0
            failed = test_failed or 0
            lines.append(f"Results: {passed}/{test_total} passed ({failed} failed)")
        lines.append("")

    # Execution section
    if runner:
        lines.append("## Execution")
        model_str = f" ({model})" if model else ""
        lines.append(f"Runner: {runner}{model_str}")
        if duration_seconds > 0:
            lines.append(f"Duration: {duration_seconds:.1f}s")
        lines.append("")

    return "\n".join(lines).strip()


def parse_task_description(description: str) -> tuple[str, list[str]] | None:
    """Parse hierarchical task description.

    Args:
        description: Full description (may include status markers)

    Returns:
        Tuple of (spec_id, task_path) or None if not a valid task description

    Examples:
        "003-terraform:T1:T2:T6" -> ("003-terraform", ["T1", "T2", "T6"])
        "003-terraform:T1:T2:T6 [DONE]" -> ("003-terraform", ["T1", "T2", "T6"])
    """
    # Strip status markers like [DONE], [RUNNING], etc.
    clean_desc = description.split("[")[0].strip()

    parts = clean_desc.split(":")
    if len(parts) < 2:
        return None

    spec_id = parts[0]
    task_path = parts[1:]

    # Validate task path has at least one task
    if not task_path or not all(p for p in task_path):
        return None

    return spec_id, task_path


def get_parent_task_path(task_path: list[str]) -> list[str] | None:
    """Get parent's task path by dropping the last segment.

    Args:
        task_path: Current task's path (e.g., ["T1", "T2", "T6"])

    Returns:
        Parent's path (e.g., ["T1", "T2"]) or None if this is a root task
    """
    if len(task_path) <= 1:
        return None
    return task_path[:-1]


def ensure_workspace_fresh(cwd: Path | None = None) -> None:
    """Update stale workspace if needed.

    In jj, when one workspace makes changes, other workspaces become "stale"
    and can't see the new changes until they're updated. This function
    ensures the current workspace is up-to-date.

    Args:
        cwd: Working directory (must be inside a jj repo)
    """
    # Run update-stale - it's a no-op if workspace isn't stale
    run_jj("workspace", "update-stale", cwd=cwd, check=False)


def find_change_by_description(
    spec_id: str,
    task_path: list[str],
    cwd: Path | None = None,
) -> str | None:
    """Find a change ID by its hierarchical description.

    Args:
        spec_id: Specification identifier
        task_path: Task path (e.g., ["T1", "T2", "T6"])
        cwd: Working directory

    Returns:
        Change ID or None if not found
    """
    # Ensure workspace is fresh before querying (handles stale working copies)
    ensure_workspace_fresh(cwd)

    desc = build_task_description(spec_id, task_path)
    # Match description with optional status suffix, but NOT child tasks
    # e.g., "spec:T001:T005*" matches "spec:T001:T005 [RUNNING]"
    # but exclude "spec:T001:T005:T006" (child task)
    revset = f'description(glob:"{desc}*") & ~description(glob:"{desc}:*") & mutable()'

    result = run_jj(
        "log", "-r", revset,
        "--no-graph", "-T", "change_id",
        "--limit", "1",
        cwd=cwd,
        check=False,
    )

    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip().split()[0]
    return None


def create_task_change(
    spec_id: str,
    task_id: str,
    parent_change: str,
    task_path: list[str] | None = None,
    cwd: Path | None = None,
) -> str:
    """Create a new change for a task.

    Args:
        spec_id: Specification identifier
        task_id: Task identifier (e.g., "T1") - used if task_path not provided
        parent_change: Parent change ID or bookmark. Never use 'main'.
        task_path: Full hierarchical path (e.g., ["T1", "T2", "T6"])
        cwd: Working directory

    Returns:
        New change ID

    Description format (hierarchical):
        {spec_id}:{task_path}
        Example: "003-terraform-hello-world:T1:T2:T6"
    """
    if not parent_change:
        raise ValueError("parent_change is required - never use main as default")

    # Use task_path if provided, otherwise create single-element path
    path = task_path if task_path else [task_id]
    description = build_task_description(spec_id, path)

    return create_change(parent=parent_change, description=description, cwd=cwd)


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

def _extract_task_id_from_description(desc: str) -> str:
    """Extract the last task ID from a description.

    Description format: "spec-id:T001:T005:T006 [STATUS]"
    Returns: "T006"
    """
    if not desc:
        return ""
    # Get first line (the task path)
    first_line = desc.split("\n")[0].strip()
    # Remove any status markers like [DONE] [RUNNING]
    first_line = first_line.split("[")[0].strip()
    # Extract last component (the task ID)
    parts = first_line.split(":")
    if parts:
        return parts[-1]
    return ""


def _extract_message_from_description(desc: str) -> str:
    """Extract the commit message from a description (everything after first line).

    Description format:
        spec-id:T001:T005:T006

        This is the commit message
        describing what was done

    Returns: "This is the commit message\ndescribing what was done"
    """
    if not desc:
        return ""
    lines = desc.split("\n")
    if len(lines) <= 1:
        return ""
    # Skip first line (task path) and any empty lines after it
    message_lines = lines[1:]
    # Strip leading empty lines
    while message_lines and not message_lines[0].strip():
        message_lines.pop(0)
    return "\n".join(message_lines).strip()


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
# Merge Commit Operations (for merge-based rollup)
# =============================================================================

def create_merge_commit(
    parent_changes: list[str],
    description: str,
    cwd: Path | None = None,
) -> str:
    """Create a merge commit with multiple parents.

    This is the core operation for parent task completion in merge-based rollup.
    The merge commit becomes the parent task's single commit.

    Args:
        parent_changes: List of change IDs to merge (children's changes)
        description: Description for the merge commit
        cwd: Working directory

    Returns:
        New change ID for the merge commit

    Raises:
        ValueError: If no parent changes provided

    Example:
        # T1 creates merge after children T2, T3 complete
        merge_id = create_merge_commit(
            [t2_change_id, t3_change_id],
            "spec:T1",
            cwd=workspace_path,
        )
        # Now working copy is the merge commit
        # T1's own work goes here
    """
    if not parent_changes:
        raise ValueError("Need at least one parent change to create merge")

    # jj new <parent1> <parent2> ... -m "description"
    args = ["new"] + parent_changes + ["-m", description]
    run_jj(*args, cwd=cwd)

    return get_change_id(cwd=cwd)


def find_completed_children(
    spec_id: str,
    task_path: list[str],
    cwd: Path | None = None,
) -> list[str]:
    """Find all completed child changes for a parent task.

    Searches for changes with descriptions matching the pattern:
    - Direct children: {spec_id}:{task_path}:{child_id}
    - Marked as done: contains [DONE]
    - Excludes grandchildren: {spec_id}:{task_path}:{child}:{grandchild}

    Args:
        spec_id: Specification ID
        task_path: Parent's task path (e.g., ["T1"])
        cwd: Working directory

    Returns:
        List of change IDs for completed children

    Example:
        # Find completed children of T1
        children = find_completed_children("my-spec", ["T1"])
        # Returns change IDs for T2, T3 if they are children of T1 and marked [DONE]
    """
    # Ensure workspace is fresh
    ensure_workspace_fresh(cwd)

    parent_desc = build_task_description(spec_id, task_path)

    # Direct children that are done
    # Match: spec:T1:T2 [DONE]
    # Exclude: spec:T1:T2:T3 (grandchildren)
    revset = (
        f'description(glob:"{parent_desc}:*") & '
        f'~description(glob:"{parent_desc}:*:*") & '
        f'description(substring:"[DONE]") & '
        f'mutable()'
    )

    result = run_jj(
        "log", "-r", revset,
        "--no-graph", "-T", 'change_id ++ "\\n"',
        cwd=cwd,
        check=False,
    )

    if result.returncode != 0:
        return []

    return [c.strip() for c in result.stdout.strip().split("\n") if c.strip()]


def find_parent_base(
    spec_id: str,
    task_path: list[str],
    source_rev: str,
    cwd: Path | None = None,
) -> str:
    """Find the base to rebase onto before running a task.

    Walks up the task tree looking for completed ancestors. If an ancestor
    has completed (has a merge commit marked [DONE]), rebase onto that.
    Otherwise, use source_rev.

    This ensures that sequential phases work correctly - Phase 2's tasks
    rebase onto Phase 1's completed merge.

    Args:
        spec_id: Specification ID
        task_path: Current task's path (e.g., ["Phase2", "T3"])
        source_rev: Fallback if no completed ancestor found
        cwd: Working directory

    Returns:
        Change ID or revset to rebase onto

    Example:
        # T3 is in Phase2, Phase1 has completed
        base = find_parent_base("my-spec", ["Phase2", "T3"], "feature-branch")
        # Returns Phase1's merge if Phase1 is done, otherwise "feature-branch"
    """
    # Ensure workspace is fresh
    ensure_workspace_fresh(cwd)

    # Walk up the tree looking for completed ancestors
    path = task_path.copy()

    while len(path) > 1:
        path = path[:-1]  # Parent's path
        parent_change = find_change_by_description(spec_id, path, cwd)
        if parent_change:
            # Check if parent is complete (has merge)
            desc = get_description(parent_change, cwd)
            if "[DONE]" in desc:
                return parent_change

    # No completed ancestor, use source_rev
    return source_rev


def find_root_task_changes(
    spec_id: str,
    cwd: Path | None = None,
) -> list[str]:
    """Find all completed root task changes for ROOT merge.

    Root tasks are top-level tasks (single-element path like "spec:T1").
    Returns only those marked [DONE].

    Args:
        spec_id: Specification ID
        cwd: Working directory

    Returns:
        List of change IDs for completed root tasks
    """
    # Ensure workspace is fresh
    ensure_workspace_fresh(cwd)

    # Root tasks have pattern spec:T* but NOT spec:T*:* (which are children)
    # And they should be marked [DONE]
    revset = (
        f'description(glob:"{spec_id}:*") & '
        f'~description(glob:"{spec_id}:*:*") & '
        f'~description(glob:"{spec_id}:ROOT*") & '  # Exclude ROOT itself
        f'~description(glob:"{spec_id}:TIP*") & '  # Exclude legacy TIP
        f'description(substring:"[DONE]") & '
        f'mutable()'
    )

    result = run_jj(
        "log", "-r", revset,
        "--no-graph", "-T", 'change_id ++ "\\n"',
        cwd=cwd,
        check=False,
    )

    if result.returncode != 0:
        return []

    return [c.strip() for c in result.stdout.strip().split("\n") if c.strip()]


# =============================================================================
# Workspace Management (for parallel execution)
# =============================================================================

def get_workspace_base_dir() -> Path:
    """Get base directory for workspaces.

    Configurable via ARBORIST_WORKSPACE_DIR env var.
    Default: ~/.arborist/workspaces

    JJ workspaces must be created OUTSIDE the main repo to work correctly.
    When created inside the repo, files don't materialize properly.

    Returns:
        Path to workspace base directory
    """
    env_dir = os.environ.get("ARBORIST_WORKSPACE_DIR")
    if env_dir:
        return Path(env_dir).expanduser()
    return Path.home() / ".arborist" / "workspaces"


def get_workspace_path(spec_id: str, task_id: str) -> Path:
    """Get workspace path for a task.

    Uses ARBORIST_WORKSPACE_DIR if set, otherwise ~/.arborist/workspaces.
    Includes repo name to avoid conflicts across repos.

    Args:
        spec_id: Specification ID
        task_id: Task ID

    Returns:
        Path to workspace directory
    """
    base = get_workspace_base_dir()
    repo_name = get_git_root().name  # Use repo directory name
    return base / repo_name / spec_id / task_id


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


def _copy_gitignored_files(source_root: Path, workspace_path: Path) -> None:
    """Copy gitignored files that are needed in workspaces.

    JJ workspaces don't include gitignored files, but some are needed
    for devcontainer/task execution (like .env files with secrets).

    Args:
        source_root: Git root containing the original files
        workspace_path: Target workspace path
    """
    import shutil

    # Files to copy if they exist
    gitignored_files = [
        ".devcontainer/.env",
    ]

    for rel_path in gitignored_files:
        source = source_root / rel_path
        target = workspace_path / rel_path

        if source.exists() and not target.exists():
            # Ensure target directory exists
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)


def setup_task_workspace(
    task_id: str,
    change_id: str,
    workspace_path: Path,
    cwd: Path | None = None,
) -> JJResult:
    """Setup a workspace for task execution.

    This:
    1. Creates workspace if needed
    2. Copies gitignored files (like .env) from git root
    3. Switches workspace to task's change

    Note: No rebasing is done here. Changes are created from the correct
    effective source (predecessor or source_rev) at pre-sync time.

    Args:
        task_id: Task identifier
        change_id: Task's change ID
        workspace_path: Path for workspace
        cwd: Working directory (git root)

    Returns:
        JJResult with operation status
    """
    workspace_name = f"ws-{task_id}"
    git_root = cwd or Path.cwd()

    # Create workspace if needed - check BOTH that jj knows about it AND path exists
    # (handles case where workspace path changed but old workspace still registered)
    workspace_path_valid = workspace_path.exists() and (workspace_path / ".jj").exists()
    if not workspace_path_valid:
        # Forget old workspace if it exists with different path
        if workspace_exists(workspace_name, cwd):
            forget_workspace(workspace_name, cwd)
        result = create_workspace(workspace_path, workspace_name, cwd)
        if not result.success:
            return result

    # Always copy gitignored files if missing (they don't come with jj workspaces)
    _copy_gitignored_files(git_root, workspace_path)

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

    return JJResult(
        success=True,
        message=f"Workspace ready at {workspace_path}",
    )


# =============================================================================
# Task Lifecycle
# =============================================================================

def mark_task_done(
    task_id: str,
    change_id: str,
    cwd: Path | None = None,
) -> None:
    """Mark task as done without squashing.

    Used for root tasks that cannot squash into immutable source_rev.

    Args:
        task_id: Task identifier
        change_id: Task's change ID
        cwd: Working directory
    """
    current_desc = get_description(change_id, cwd)
    if "[DONE]" not in current_desc:
        done_desc = current_desc.replace(f":{task_id}", f":{task_id} [DONE]")
        describe_change(done_desc, change_id, cwd)


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
    # Query for all changes with spec description pattern (new format: spec_id:T1:T2:...)
    revset = f'description(glob:"{spec_id}:*") & mutable()'

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

        # Parse using hierarchical format
        parsed = parse_task_description(desc)
        if not parsed:
            continue

        _, task_path = parsed
        # Use last element as task_id for backwards compat
        task_id = task_path[-1] if task_path else ""

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
            parent_change=None,  # Can derive from jj graph if needed
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
