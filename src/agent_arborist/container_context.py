"""Container context detection for subprocess execution.

This module helps commands detect if their subprocesses (runners, tests) should
execute inside a devcontainer.

Key insight: Arborist commands always run on host. They wrap subprocess calls
(runner commands, test commands) with devcontainer exec when needed.
"""

import logging
import os
from pathlib import Path

from agent_arborist.container_runner import ContainerMode, has_devcontainer

logger = logging.getLogger(__name__)


def is_inside_container() -> bool:
    """Detect if we are currently executing inside a container.

    Uses multiple detection methods for reliability:
    1. /.dockerenv file (Docker containers)
    2. /proc/1/cgroup contains 'docker' or 'lxc' (Linux containers)
    3. REMOTE_CONTAINERS env var (VS Code devcontainers)

    Returns:
        True if inside any container, False otherwise

    Note:
        This should NEVER be True for arborist commands - they always run on host.
        If True, it indicates a misconfiguration.
    """
    # Method 1: Docker marker file
    if Path("/.dockerenv").exists():
        return True

    # Method 2: cgroup check (Linux only)
    try:
        cgroup_path = Path("/proc/1/cgroup")
        if cgroup_path.exists():
            cgroup = cgroup_path.read_text()
            if "docker" in cgroup or "lxc" in cgroup:
                return True
    except (FileNotFoundError, PermissionError):
        pass

    # Method 3: VS Code devcontainer marker
    if os.environ.get("REMOTE_CONTAINERS") == "true":
        return True

    return False


def should_use_container(worktree: Path, mode: ContainerMode) -> bool:
    """Determine if subprocesses should run in a container.

    Args:
        worktree: Target project worktree path
        mode: Container mode configuration

    Returns:
        True if subprocesses should run in container, False if on host

    Raises:
        RuntimeError: If mode is ENABLED but no devcontainer found
    """
    # WARNING: Detect misconfiguration
    if is_inside_container():
        logger.warning(
            "Arborist command running inside container - should run on host! "
            "This may cause issues with worktree management and git operations."
        )
        # Continue anyway (defensive programming)
        return False

    # Check if container mode disabled
    if mode == ContainerMode.DISABLED:
        return False

    # Check if target has devcontainer
    needs = has_devcontainer(worktree)

    if mode == ContainerMode.ENABLED and not needs:
        raise RuntimeError(
            f"Container mode is 'enabled' but {worktree} has no .devcontainer/. "
            "Either add a .devcontainer/ to the target project or use --container-mode auto"
        )

    # AUTO mode: use container if available
    return needs


def wrap_subprocess_command(
    cmd: list[str],
    worktree: Path,
    container_mode: ContainerMode,
) -> list[str]:
    """Wrap subprocess command with devcontainer exec if needed.

    This is the core function that wraps subprocess commands (runners, tests)
    to execute inside containers when appropriate.

    Args:
        cmd: The subprocess command to execute
        worktree: Target worktree path
        container_mode: Container mode configuration

    Returns:
        Wrapped command list if container needed, original command otherwise

    Example:
        # Without container:
        wrap_subprocess_command(["claude", "-p", "prompt"], worktree, DISABLED)
        # Returns: ["claude", "-p", "prompt"]

        # With container:
        wrap_subprocess_command(["claude", "-p", "prompt"], worktree, AUTO)
        # Returns: ["devcontainer", "exec", "--workspace-folder", "/path", "claude", "-p", "prompt"]
    """
    if not should_use_container(worktree, container_mode):
        return cmd

    # Wrap with devcontainer exec
    return [
        "devcontainer",
        "exec",
        "--workspace-folder",
        str(worktree.resolve()),
        *cmd
    ]


def get_container_mode_from_env() -> ContainerMode:
    """Get container mode from environment variable.

    Returns:
        ContainerMode from ARBORIST_CONTAINER_MODE env var, defaults to AUTO
    """
    container_mode_str = os.environ.get("ARBORIST_CONTAINER_MODE", "auto")
    try:
        return ContainerMode(container_mode_str)
    except ValueError:
        logger.warning(f"Invalid ARBORIST_CONTAINER_MODE: {container_mode_str}, using auto")
        return ContainerMode.AUTO
