"""Git operations for task-based worktree workflow."""

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TYPE_CHECKING

from agent_arborist.home import get_arborist_home, get_git_root

if TYPE_CHECKING:
    from agent_arborist.branch_manifest import BranchManifest


@dataclass
class GitResult:
    """Result from a git operation."""

    success: bool
    message: str
    error: str | None = None


@dataclass
class MergeResult:
    """Result from a merge operation."""

    success: bool
    message: str
    conflicts: list[str] | None = None
    error: str | None = None


def _run_git(*args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    """Run a git command."""
    cmd = ["git", *args]
    return subprocess.run(
        cmd,
        cwd=cwd or get_git_root(),
        capture_output=True,
        text=True,
        check=check,
    )


def branch_exists(branch: str, cwd: Path | None = None) -> bool:
    """Check if a branch exists."""
    result = _run_git("rev-parse", "--verify", branch, cwd=cwd, check=False)
    return result.returncode == 0


def find_worktree_for_branch(branch: str, cwd: Path | None = None) -> Path | None:
    """Find existing worktree path for a branch, if any.

    Returns the worktree path if one exists for the branch, None otherwise.
    """
    result = _run_git("worktree", "list", "--porcelain", cwd=cwd, check=False)
    if result.returncode != 0:
        return None

    # Parse porcelain output: blocks separated by blank lines
    # Each block has: worktree <path>\nHEAD <sha>\nbranch <ref>\n
    current_path = None
    for line in result.stdout.split("\n"):
        if line.startswith("worktree "):
            current_path = Path(line[9:])
        elif line.startswith("branch refs/heads/"):
            worktree_branch = line[18:]  # Strip "branch refs/heads/"
            if worktree_branch == branch and current_path:
                return current_path
            current_path = None

    return None


def find_parent_branch(task_branch: str, cwd: Path | None = None) -> str:
    """Walk up hierarchy to find first existing branch.

    Given "spec/002-feature_T001_T004", tries:
    1. spec/002-feature_T001 (remove last _TXXX)
    2. spec/002-feature (the spec branch)
    3. main (or master)
    """
    current = task_branch

    # First try removing last _TXXX segment (underscore-separated task IDs)
    while "_" in current:
        current = current.rsplit("_", 1)[0]
        if branch_exists(current, cwd):
            return current

    # Then try removing the last path segment (spec/xxx -> spec)
    while "/" in current:
        current = current.rsplit("/", 1)[0]
        if branch_exists(current, cwd):
            return current

    # Fall back to main branch
    if branch_exists("main", cwd):
        return "main"
    if branch_exists("master", cwd):
        return "master"

    raise ValueError(f"No parent branch found for {task_branch}")


def create_task_branch(task_branch: str, parent_branch: str, cwd: Path | None = None) -> GitResult:
    """Create a new branch from parent if it doesn't exist."""
    if branch_exists(task_branch, cwd):
        return GitResult(success=True, message=f"Branch {task_branch} already exists")

    try:
        _run_git("branch", task_branch, parent_branch, cwd=cwd)
        return GitResult(success=True, message=f"Created branch {task_branch} from {parent_branch}")
    except subprocess.CalledProcessError as e:
        return GitResult(success=False, message="Failed to create branch", error=e.stderr)


def get_worktree_path(spec_id: str, task_id: str) -> Path:
    """Return worktree path: .arborist/worktrees/<spec-id>/<task-id>."""
    arborist_home = get_arborist_home()
    return arborist_home / "worktrees" / spec_id / task_id


def get_git_root_from_worktree(worktree_path: Path) -> Path | None:
    """Get git repository root from within a worktree context.

    Args:
        worktree_path: Path to worktree directory

    Returns:
        Path to git repository root, or None if cannot determine
    """
    git_file = worktree_path / ".git"
    if not git_file.exists():
        return None

    try:
        content = git_file.read_text().strip()
        if content.startswith("gitdir: "):
            git_dir_path = content[8:]
            git_dir = Path(git_dir_path).resolve()
            
            # Worktree gitdir is at: repo/.git/worktrees/<name>
            # Repo root is two levels up from worktrees/
            if "worktrees" in str(git_dir):
                parts = git_dir.parts
                worktrees_idx = parts.index("worktrees")
                if worktrees_idx > 0:
                    root = Path(*parts[:worktrees_idx])
                    return root
            
            return None
    except Exception:
        return None
    
    return None


def get_git_root_or_current() -> Path:
    """Get git root, searching from either current dir or worktree.

    Tries:
    1. Get root from current directory (git rev-parse --show-toplevel)
    2. If in worktree, parse .git file to find repo root

    Returns:
        Path to git repository root

    Raises:
        ArboristHomeError: If cannot determine git root
    """
    from agent_arborist.home import get_git_root
    
    git_root = get_git_root()
    if git_root:
        return git_root
    
    # Try worktree context
    import os
    worktree_env = os.environ.get("ARBORIST_WORKTREE")
    if worktree_env:
        worktree_path = Path(worktree_env)
        worktree_root = get_git_root_from_worktree(worktree_path)
        if worktree_root:
            return worktree_root
    
    raise ArboristHomeError(
        "Cannot determine git repository root. "
        "Are you in a git repository or worktree?"
    )


def find_manifest_path(spec_id: str, git_root: Path | None = None) -> Path | None:
    """Find manifest file using discovery strategy.

    Args:
        spec_id: Specification ID for the DAG
        git_root: Git repository root (optional, will auto-detect if not provided)

    Returns:
        Path to manifest file, or None if not found

    Search order:
    1. {git_root}/.arborist/dagu/dags/{spec_id}.json (tracked location)
    2. {git_root}/.arborist/{spec_id}.json
    3. {git_root}/specs/{spec_id}/manifest.json
    """
    if git_root is None:
        try:
            git_root = get_git_root_or_current()
        except Exception:
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


def worktree_exists(worktree_path: Path) -> bool:
    """Check if a worktree exists at the given path."""
    return worktree_path.exists() and (worktree_path / ".git").exists()


def create_worktree(task_branch: str, worktree_path: Path, cwd: Path | None = None) -> GitResult:
    """Create a worktree for the task branch."""
    if worktree_exists(worktree_path):
        return GitResult(success=True, message=f"Worktree already exists at {worktree_path}")

    # Ensure parent directory exists
    worktree_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        _run_git("worktree", "add", str(worktree_path), task_branch, cwd=cwd)
        return GitResult(success=True, message=f"Created worktree at {worktree_path}")
    except subprocess.CalledProcessError as e:
        return GitResult(success=False, message="Failed to create worktree", error=e.stderr)


def sync_from_parent(task_branch: str, parent_branch: str, worktree_path: Path) -> GitResult:
    """Sync task branch with parent (merge parent into task)."""
    try:
        # Fetch latest
        _run_git("fetch", "origin", cwd=worktree_path, check=False)

        # Merge parent into task branch
        result = _run_git("merge", parent_branch, "--no-edit", cwd=worktree_path, check=False)

        if result.returncode == 0:
            return GitResult(success=True, message=f"Synced with {parent_branch}")

        # Check for conflicts
        if "CONFLICT" in result.stdout or "conflict" in result.stderr.lower():
            return GitResult(
                success=False,
                message="Merge conflicts detected",
                error=result.stdout + result.stderr,
            )

        return GitResult(success=False, message="Sync failed", error=result.stderr)
    except subprocess.CalledProcessError as e:
        return GitResult(success=False, message="Sync failed", error=e.stderr)


def get_current_branch(cwd: Path | None = None) -> str:
    """Get the current branch name."""
    result = _run_git("rev-parse", "--abbrev-ref", "HEAD", cwd=cwd)
    return result.stdout.strip()


def merge_to_parent(
    task_branch: str,
    parent_branch: str,
    cwd: Path | None = None,
) -> MergeResult:
    """Merge task branch into parent with --no-ff.

    Uses an existing worktree for the parent branch if available,
    otherwise creates a temporary one. This allows child tasks to
    merge back to a parent whose worktree is still active.
    """
    import tempfile
    import shutil

    git_root = cwd or get_git_root()

    # Check if a worktree already exists for the parent branch
    existing_worktree = find_worktree_for_branch(parent_branch, cwd=git_root)
    using_existing = existing_worktree is not None

    if using_existing:
        parent_worktree = existing_worktree
        temp_dir = None
    else:
        # Create a temporary worktree for the parent branch
        temp_dir = tempfile.mkdtemp(prefix="arborist_merge_")
        parent_worktree = Path(temp_dir) / "parent"

    try:
        if not using_existing:
            # Create worktree for parent branch
            _run_git("worktree", "add", str(parent_worktree), parent_branch, cwd=git_root)

        # Attempt merge in the worktree
        result = _run_git(
            "merge", "--no-ff", task_branch,
            "-m", f"Merge {task_branch} into {parent_branch}",
            cwd=parent_worktree,
            check=False,
        )

        if result.returncode == 0:
            return MergeResult(success=True, message=f"Merged {task_branch} into {parent_branch}")

        # Check for conflicts
        conflict_result = _run_git("diff", "--name-only", "--diff-filter=U", cwd=parent_worktree, check=False)
        conflicts = [f.strip() for f in conflict_result.stdout.strip().split("\n") if f.strip()]

        if conflicts:
            # Abort the merge before cleanup
            _run_git("merge", "--abort", cwd=parent_worktree, check=False)
            return MergeResult(
                success=False,
                message="Merge conflicts detected",
                conflicts=conflicts,
                error=result.stderr,
            )

        return MergeResult(success=False, message="Merge failed", error=result.stderr)
    except subprocess.CalledProcessError as e:
        return MergeResult(success=False, message="Merge failed", error=e.stderr)
    finally:
        # Only clean up if we created a temporary worktree
        if not using_existing and temp_dir:
            try:
                _run_git("worktree", "remove", str(parent_worktree), "--force", cwd=git_root, check=False)
            except Exception:
                pass
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass


def get_conflict_files(cwd: Path | None = None) -> list[str]:
    """Get list of files with merge conflicts."""
    result = _run_git("diff", "--name-only", "--diff-filter=U", cwd=cwd, check=False)
    return [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]


def abort_merge(cwd: Path | None = None) -> GitResult:
    """Abort an in-progress merge."""
    try:
        _run_git("merge", "--abort", cwd=cwd)
        return GitResult(success=True, message="Merge aborted")
    except subprocess.CalledProcessError as e:
        return GitResult(success=False, message="Failed to abort merge", error=e.stderr)


def cleanup_task(
    task_branch: str,
    worktree_path: Path,
    delete_branch: bool = True,
    cwd: Path | None = None,
) -> GitResult:
    """Remove worktree and optionally delete branch."""
    git_root = cwd or get_git_root()
    errors = []

    # Remove worktree
    if worktree_exists(worktree_path):
        try:
            _run_git("worktree", "remove", str(worktree_path), "--force", cwd=git_root)
        except subprocess.CalledProcessError as e:
            errors.append(f"Failed to remove worktree: {e.stderr}")

    # Delete branch if requested
    if delete_branch and branch_exists(task_branch, git_root):
        try:
            # Use -d (safe delete) first, fall back to -D if needed
            result = _run_git("branch", "-d", task_branch, cwd=git_root, check=False)
            if result.returncode != 0:
                # Force delete if safe delete fails (branch not fully merged)
                _run_git("branch", "-D", task_branch, cwd=git_root)
        except subprocess.CalledProcessError as e:
            errors.append(f"Failed to delete branch: {e.stderr}")

    if errors:
        return GitResult(success=False, message="Cleanup had errors", error="\n".join(errors))

    return GitResult(success=True, message=f"Cleaned up {task_branch}")


def detect_test_command(worktree: Path) -> str | None:
    """Auto-detect test command based on project files."""
    if (worktree / "pyproject.toml").exists() or (worktree / "pytest.ini").exists():
        return "pytest"
    if (worktree / "package.json").exists():
        return "npm test"
    if (worktree / "Makefile").exists():
        # Check if Makefile has a test target
        makefile_content = (worktree / "Makefile").read_text()
        if "test:" in makefile_content:
            return "make test"
    if (worktree / "Cargo.toml").exists():
        return "cargo test"
    if (worktree / "go.mod").exists():
        return "go test ./..."
    return None


def run_tests(
    worktree: Path,
    test_cmd: str | None = None,
    container_cmd_prefix: list[str] | None = None,
) -> GitResult:
    """Run tests in the worktree.

    Args:
        worktree: Path to worktree
        test_cmd: Test command to run (auto-detected if None)
        container_cmd_prefix: Optional devcontainer exec prefix for running in container

    Returns:
        GitResult with success status and output
    """
    cmd = test_cmd or detect_test_command(worktree)

    if not cmd:
        return GitResult(success=True, message="No test command detected, skipping tests")

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
                cwd=worktree,
                capture_output=True,
                text=True,
            )

        if result.returncode == 0:
            return GitResult(success=True, message="Tests passed")

        return GitResult(
            success=False,
            message="Tests failed",
            error=result.stdout + result.stderr,
        )
    except Exception as e:
        return GitResult(success=False, message="Failed to run tests", error=str(e))


def create_all_branches_from_manifest(manifest: "BranchManifest", cwd: Path | None = None) -> GitResult:
    """Create all branches from a manifest in topological order.

    Creates the base branch first, then all task branches in dependency order.

    Args:
        manifest: BranchManifest with pre-computed branch names
        cwd: Working directory for git operations

    Returns:
        GitResult with success/failure status
    """
    from agent_arborist.branch_manifest import topological_sort

    created = []
    errors = []

    # Create base branch from source branch
    if not branch_exists(manifest.base_branch, cwd):
        result = create_task_branch(manifest.base_branch, manifest.source_branch, cwd)
        if result.success:
            created.append(manifest.base_branch)
        else:
            return GitResult(
                success=False,
                message=f"Failed to create base branch {manifest.base_branch}",
                error=result.error,
            )

    # Create task branches in topological order (parents before children)
    task_order = topological_sort(manifest.tasks)

    for task_id in task_order:
        task_info = manifest.tasks[task_id]

        if branch_exists(task_info.branch, cwd):
            continue  # Already exists

        result = create_task_branch(task_info.branch, task_info.parent_branch, cwd)
        if result.success:
            created.append(task_info.branch)
        else:
            errors.append(f"{task_id}: {result.error}")

    if errors:
        return GitResult(
            success=False,
            message=f"Created {len(created)} branches, {len(errors)} failed",
            error="\n".join(errors),
        )

    return GitResult(
        success=True,
        message=f"Created {len(created)} branches ({len(manifest.tasks)} tasks + base)",
    )


def sync_task(
    task_branch: str,
    parent_branch: str,
    worktree_path: Path,
    cwd: Path | None = None,
) -> GitResult:
    """Create worktree and sync from parent branch.

    This is the simplified task setup - branches must already exist.
    Called by `arborist task sync`.

    Args:
        task_branch: The task's branch name (from manifest)
        parent_branch: The parent's branch name (from manifest)
        worktree_path: Path for the worktree
        cwd: Working directory for git operations

    Returns:
        GitResult with success/failure status
    """
    # Create worktree
    result = create_worktree(task_branch, worktree_path, cwd)
    if not result.success:
        return result

    # Sync from parent
    result = sync_from_parent(task_branch, parent_branch, worktree_path)
    if not result.success:
        return result

    # Copy .devcontainer/.env from git root to worktree if it exists
    git_root = cwd or get_git_root()
    source_env = git_root / ".devcontainer" / ".env"

    if source_env.exists():
        import shutil

        # Ensure .devcontainer directory exists in worktree
        worktree_devcontainer = worktree_path / ".devcontainer"
        worktree_devcontainer.mkdir(parents=True, exist_ok=True)

        # Copy the .env file
        target_env = worktree_devcontainer / ".env"
        try:
            shutil.copy2(source_env, target_env)
        except Exception as e:
            # Non-fatal: log but don't fail the sync
            import sys
            print(f"Warning: Failed to copy .devcontainer/.env: {e}", file=sys.stderr)

    return GitResult(
        success=True,
        message=f"Task synced at {worktree_path}",
    )
