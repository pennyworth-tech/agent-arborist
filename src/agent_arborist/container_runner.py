"""DevContainer detection and command generation for target projects.

This module provides:
1. Detection functions to check if target project has .devcontainer/
2. Simple command builders for devcontainer CLI operations

Based on spike test validation (see docs/devcontainer-implementation-review.md Part 4):
- bash -lc wrapper NOT needed - Claude Code is in PATH
- Environment variables from .env inherited by all exec commands
- Working directory defaults correctly to /workspaces/<folder-name>
"""

import shutil
import subprocess
from enum import Enum
from pathlib import Path

from agent_arborist.home import get_git_root


class ContainerMode(Enum):
    """Container execution mode for DAG steps."""

    AUTO = "auto"  # Use devcontainer if target has .devcontainer/
    ENABLED = "enabled"  # Require devcontainer, fail if not present
    DISABLED = "disabled"  # Never use devcontainer


def has_devcontainer(repo_path: Path | None = None) -> bool:
    """Check if target project has a .devcontainer/ directory.

    Args:
        repo_path: Path to target repo. Defaults to git root.

    Returns:
        True if .devcontainer/ exists with valid config.
    """
    repo_path = repo_path or get_git_root()
    devcontainer_dir = repo_path / ".devcontainer"

    if not devcontainer_dir.is_dir():
        return False

    # Check for devcontainer.json or Dockerfile
    has_config = (devcontainer_dir / "devcontainer.json").exists()
    has_dockerfile = (devcontainer_dir / "Dockerfile").exists()

    return has_config or has_dockerfile


def should_use_container(mode: ContainerMode, repo_path: Path | None = None) -> bool:
    """Determine if container mode should be used.

    Args:
        mode: The configured container mode.
        repo_path: Path to target repo.

    Returns:
        True if commands should run in devcontainer.

    Raises:
        RuntimeError: If mode is ENABLED but no devcontainer found.
    """
    if mode == ContainerMode.DISABLED:
        return False

    has_dc = has_devcontainer(repo_path)

    if mode == ContainerMode.ENABLED and not has_dc:
        raise RuntimeError(
            "Container mode is 'enabled' but target project has no .devcontainer/. "
            "Either add a .devcontainer/ to the target project or use --container-mode auto"
        )

    if mode == ContainerMode.AUTO:
        return has_dc

    return True  # mode == ENABLED and has_dc


def check_devcontainer_cli() -> tuple[bool, str]:
    """Check if devcontainer CLI is installed.

    Returns:
        Tuple of (is_installed, version_or_error)
    """
    if not shutil.which("devcontainer"):
        return (
            False,
            "devcontainer CLI not found. Install: npm install -g @devcontainers/cli",
        )

    try:
        result = subprocess.run(
            ["devcontainer", "--version"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return True, result.stdout.strip()
        return False, result.stderr.strip()
    except Exception as e:
        return False, str(e)


def check_docker() -> tuple[bool, str]:
    """Check if Docker is running.

    Returns:
        Tuple of (is_running, version_or_error)
    """
    if not shutil.which("docker"):
        return False, "Docker not found in PATH"

    try:
        result = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return True, result.stdout.strip()
        return False, "Docker daemon not running"
    except Exception as e:
        return False, str(e)


# Command builders for DAG generation
# These generate shell commands that DAGU will execute


def get_devcontainer_exec_prefix(workspace_folder: Path) -> list[str]:
    """Get the devcontainer exec command prefix for running commands in container.

    Args:
        workspace_folder: Path to the workspace folder

    Returns:
        Command prefix as list of strings for subprocess
    """
    return ["devcontainer", "exec", "--workspace-folder", str(workspace_folder)]


def devcontainer_up_command(worktree_env_var: str = "${ARBORIST_WORKTREE}") -> str:
    """Generate shell command for container-up step.

    Args:
        worktree_env_var: Environment variable reference for worktree path

    Returns:
        Shell command string for starting devcontainer

    Note:
        Environment variables from .env are inherited by all exec commands.
        No bash -lc wrapper needed (validated in spike tests).
    """
    return f'devcontainer up --workspace-folder "{worktree_env_var}"'


def devcontainer_exec_command(
    command: str,
    worktree_env_var: str = "${ARBORIST_WORKTREE}",
) -> str:
    """Generate shell command wrapping a command in devcontainer exec.

    Args:
        command: The command to execute inside the container
        worktree_env_var: Environment variable reference for worktree path

    Returns:
        Shell command string for executing in devcontainer

    Note:
        Working directory defaults to /workspaces/<folder-name>.
        Claude Code at /home/vscode/.local/bin/claude is in PATH.
        No bash -lc wrapper needed (validated in spike tests).
    """
    return f'devcontainer exec --workspace-folder "{worktree_env_var}" {command}'


def devcontainer_down_command(worktree_env_var: str = "${ARBORIST_WORKTREE}") -> str:
    """Generate shell command for container-down step.

    Args:
        worktree_env_var: Environment variable reference for worktree path

    Returns:
        Shell command string for stopping devcontainer

    Note:
        Uses docker ps filter to find container by devcontainer.local_folder label.
        The '|| true' ensures the command succeeds even if no container is running.
    """
    return (
        f"docker stop $(docker ps -q --filter "
        f'label=devcontainer.local_folder="{worktree_env_var}") 2>/dev/null || true'
    )
