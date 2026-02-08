"""Git operations for sequential task execution.

This module provides plain git operations for Agent Arborist's
sequential task execution model.

Key concepts:
- Single worktree (the main repo)
- Linear commit history
- No parallel execution, no workspaces
- DAGU handles orchestration and state
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path

from agent_arborist.home import get_git_root


class GitError(Exception):
    """Base exception for git operations."""
    pass


@dataclass
class GitResult:
    """Result from a git operation."""
    success: bool
    message: str
    stdout: str = ""
    stderr: str = ""
    error: str | None = None


def run_git(
    *args: str,
    cwd: Path | None = None,
    check: bool = True,
    capture_output: bool = True,
) -> subprocess.CompletedProcess:
    """Run a git command.

    Args:
        *args: Command arguments (e.g., "status", "--short")
        cwd: Working directory
        check: Raise on non-zero exit
        capture_output: Capture stdout/stderr

    Returns:
        CompletedProcess with stdout/stderr

    Raises:
        subprocess.CalledProcessError: If check=True and command fails
    """
    cmd = ["git", *args]
    return subprocess.run(
        cmd,
        cwd=cwd or get_git_root(),
        capture_output=capture_output,
        text=True,
        check=check,
    )


def is_git_repo(cwd: Path | None = None) -> bool:
    """Check if current directory is a git repository."""
    try:
        result = run_git("rev-parse", "--git-dir", cwd=cwd, check=False)
        return result.returncode == 0
    except Exception:
        return False


def get_current_branch(cwd: Path | None = None) -> str | None:
    """Get the current branch name.

    Args:
        cwd: Working directory

    Returns:
        Branch name or None if detached HEAD
    """
    result = run_git(
        "rev-parse", "--abbrev-ref", "HEAD",
        cwd=cwd,
        check=False,
    )
    if result.returncode == 0:
        branch = result.stdout.strip()
        return None if branch == "HEAD" else branch
    return None


def get_current_commit(cwd: Path | None = None) -> str | None:
    """Get the current commit SHA.

    Args:
        cwd: Working directory

    Returns:
        Commit SHA or None
    """
    result = run_git(
        "rev-parse", "HEAD",
        cwd=cwd,
        check=False,
    )
    if result.returncode == 0:
        return result.stdout.strip()
    return None


def get_short_commit(cwd: Path | None = None) -> str | None:
    """Get the short (7 char) commit SHA.

    Args:
        cwd: Working directory

    Returns:
        Short commit SHA or None
    """
    result = run_git(
        "rev-parse", "--short", "HEAD",
        cwd=cwd,
        check=False,
    )
    if result.returncode == 0:
        return result.stdout.strip()
    return None


def has_uncommitted_changes(cwd: Path | None = None) -> bool:
    """Check if there are uncommitted changes.

    Args:
        cwd: Working directory

    Returns:
        True if there are staged or unstaged changes
    """
    result = run_git("status", "--porcelain", cwd=cwd, check=False)
    return bool(result.stdout.strip())


def get_changed_files(cwd: Path | None = None) -> list[str]:
    """Get list of changed files (staged and unstaged).

    Args:
        cwd: Working directory

    Returns:
        List of file paths
    """
    result = run_git("status", "--porcelain", cwd=cwd, check=False)
    if result.returncode != 0:
        return []

    files = []
    for line in result.stdout.strip().split("\n"):
        if line.strip():
            # Format: XY filename
            # X = staged status, Y = unstaged status
            files.append(line[3:].strip())
    return files


def stage_all(cwd: Path | None = None) -> GitResult:
    """Stage all changes.

    Args:
        cwd: Working directory

    Returns:
        GitResult with operation status
    """
    result = run_git("add", "-A", cwd=cwd, check=False)
    return GitResult(
        success=result.returncode == 0,
        message="Staged all changes" if result.returncode == 0 else "Failed to stage",
        stdout=result.stdout,
        stderr=result.stderr,
        error=result.stderr if result.returncode != 0 else None,
    )


def commit(
    message: str,
    cwd: Path | None = None,
    allow_empty: bool = False,
) -> GitResult:
    """Create a commit with staged changes.

    Args:
        message: Commit message
        cwd: Working directory
        allow_empty: Allow empty commits

    Returns:
        GitResult with operation status
    """
    args = ["commit", "-m", message]
    if allow_empty:
        args.append("--allow-empty")

    result = run_git(*args, cwd=cwd, check=False)

    success = result.returncode == 0
    if not success and "nothing to commit" in result.stdout:
        # Treat as success if nothing to commit
        return GitResult(
            success=True,
            message="Nothing to commit",
            stdout=result.stdout,
            stderr=result.stderr,
        )

    return GitResult(
        success=success,
        message="Committed" if success else "Failed to commit",
        stdout=result.stdout,
        stderr=result.stderr,
        error=result.stderr if not success else None,
    )


def stage_and_commit(
    message: str,
    cwd: Path | None = None,
) -> GitResult:
    """Stage all changes and commit.

    This is the main operation for task completion.

    Args:
        message: Commit message
        cwd: Working directory

    Returns:
        GitResult with operation status
    """
    # Stage all changes
    stage_result = stage_all(cwd)
    if not stage_result.success:
        return stage_result

    # Check if there are changes to commit
    if not has_uncommitted_changes(cwd):
        return GitResult(
            success=True,
            message="Nothing to commit",
        )

    # Commit
    return commit(message, cwd)


def create_branch(
    branch_name: str,
    start_point: str | None = None,
    cwd: Path | None = None,
) -> GitResult:
    """Create a new branch.

    Args:
        branch_name: Name for the new branch
        start_point: Starting commit/branch (default: HEAD)
        cwd: Working directory

    Returns:
        GitResult with operation status
    """
    args = ["checkout", "-b", branch_name]
    if start_point:
        args.append(start_point)

    result = run_git(*args, cwd=cwd, check=False)
    return GitResult(
        success=result.returncode == 0,
        message=f"Created branch {branch_name}" if result.returncode == 0 else "Failed",
        stdout=result.stdout,
        stderr=result.stderr,
        error=result.stderr if result.returncode != 0 else None,
    )


def checkout_branch(
    branch_name: str,
    cwd: Path | None = None,
) -> GitResult:
    """Checkout an existing branch.

    Args:
        branch_name: Branch to checkout
        cwd: Working directory

    Returns:
        GitResult with operation status
    """
    result = run_git("checkout", branch_name, cwd=cwd, check=False)
    return GitResult(
        success=result.returncode == 0,
        message=f"Checked out {branch_name}" if result.returncode == 0 else "Failed",
        stdout=result.stdout,
        stderr=result.stderr,
        error=result.stderr if result.returncode != 0 else None,
    )


def push_branch(
    branch_name: str | None = None,
    remote: str = "origin",
    set_upstream: bool = True,
    cwd: Path | None = None,
) -> GitResult:
    """Push branch to remote.

    Args:
        branch_name: Branch to push (default: current branch)
        remote: Remote name
        set_upstream: Set upstream tracking
        cwd: Working directory

    Returns:
        GitResult with operation status
    """
    args = ["push", remote]
    if branch_name:
        args.append(branch_name)
    if set_upstream:
        args.insert(1, "-u")

    result = run_git(*args, cwd=cwd, check=False)
    return GitResult(
        success=result.returncode == 0,
        message="Pushed" if result.returncode == 0 else "Failed to push",
        stdout=result.stdout,
        stderr=result.stderr,
        error=result.stderr if result.returncode != 0 else None,
    )


def get_commit_log(
    limit: int = 10,
    format_str: str = "%h %s",
    cwd: Path | None = None,
) -> list[str]:
    """Get commit log.

    Args:
        limit: Maximum commits to return
        format_str: Git log format string
        cwd: Working directory

    Returns:
        List of formatted commit strings
    """
    result = run_git(
        "log", f"-{limit}", f"--format={format_str}",
        cwd=cwd,
        check=False,
    )
    if result.returncode != 0:
        return []

    return [line for line in result.stdout.strip().split("\n") if line]


def get_diff_stat(cwd: Path | None = None) -> str:
    """Get diff statistics for uncommitted changes.

    Args:
        cwd: Working directory

    Returns:
        Diff stat output
    """
    result = run_git("diff", "--stat", cwd=cwd, check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


def count_changed_files(cwd: Path | None = None) -> int:
    """Count number of changed files.

    Args:
        cwd: Working directory

    Returns:
        Number of changed files
    """
    return len(get_changed_files(cwd))


# =============================================================================
# Task-specific helpers
# =============================================================================

def build_commit_message(
    spec_id: str,
    task_id: str,
    summary: str = "",
    files_changed: int = 0,
) -> str:
    """Build a commit message for a task.

    Args:
        spec_id: Specification ID
        task_id: Task identifier
        summary: Summary of work done
        files_changed: Number of files changed

    Returns:
        Formatted commit message
    """
    lines = [f"{spec_id}:{task_id}"]

    if summary:
        lines.append("")
        lines.append(summary[:500])  # Truncate long summaries

    if files_changed:
        lines.append("")
        lines.append(f"Files changed: {files_changed}")

    return "\n".join(lines)


def commit_task(
    spec_id: str,
    task_id: str,
    summary: str = "",
    cwd: Path | None = None,
) -> GitResult:
    """Commit changes for a completed task.

    This stages all changes and creates a commit with a formatted message.

    Args:
        spec_id: Specification ID
        task_id: Task identifier
        summary: Summary of work done
        cwd: Working directory

    Returns:
        GitResult with operation status
    """
    # Count files before staging
    files_changed = count_changed_files(cwd)

    # Build commit message
    message = build_commit_message(spec_id, task_id, summary, files_changed)

    # Stage and commit
    return stage_and_commit(message, cwd)


# =============================================================================
# Test utilities
# =============================================================================

def detect_test_command(workspace: Path) -> str | None:
    """Auto-detect test command based on project files.

    Args:
        workspace: Path to workspace directory

    Returns:
        Test command string, or None if no test command detected
    """
    if (workspace / "pyproject.toml").exists() or (workspace / "pytest.ini").exists():
        return "pytest"
    if (workspace / "package.json").exists():
        return "npm test"
    if (workspace / "Makefile").exists():
        makefile_content = (workspace / "Makefile").read_text()
        if "test:" in makefile_content:
            return "make test"
    if (workspace / "Cargo.toml").exists():
        return "cargo test"
    if (workspace / "go.mod").exists():
        return "go test ./..."
    return None


def run_tests(
    cwd: Path,
    test_cmd: str | None = None,
    container_cmd_prefix: list[str] | None = None,
    timeout: int | None = None,
) -> GitResult:
    """Run tests in the workspace.

    Args:
        cwd: Working directory
        test_cmd: Test command to run (auto-detected if None)
        container_cmd_prefix: Optional devcontainer exec prefix
        timeout: Command timeout in seconds

    Returns:
        GitResult with success status and output
    """
    cmd = test_cmd or detect_test_command(cwd)

    if not cmd:
        return GitResult(
            success=True,
            message="No test command detected, skipping tests",
        )

    try:
        if container_cmd_prefix:
            full_cmd = container_cmd_prefix + ["bash", "-c", cmd]
            result = subprocess.run(
                full_cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        else:
            result = subprocess.run(
                cmd,
                shell=True,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

        if result.returncode == 0:
            return GitResult(
                success=True,
                message="Tests passed",
                stdout=result.stdout,
                stderr=result.stderr,
            )

        return GitResult(
            success=False,
            message="Tests failed",
            stdout=result.stdout,
            stderr=result.stderr,
            error=result.stdout + result.stderr,
        )
    except subprocess.TimeoutExpired:
        return GitResult(
            success=False,
            message="Tests timed out",
            error=f"Timeout after {timeout}s",
        )
    except Exception as e:
        return GitResult(
            success=False,
            message="Failed to run tests",
            error=str(e),
        )
