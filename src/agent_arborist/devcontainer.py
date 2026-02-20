# Copyright 2026 Pennyworth Technologies, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Devcontainer detection, mode resolution, and CLI wrapper."""

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class DevcontainerError(Exception):
    """Base error for container operations."""


class DevcontainerNotFoundError(DevcontainerError):
    """Raised when container mode is 'enabled' but no .devcontainer/ exists."""


def has_devcontainer(cwd: Path) -> bool:
    """Check if a devcontainer.json exists in the workspace."""
    return (cwd / ".devcontainer" / "devcontainer.json").is_file()


def should_use_container(mode: str, cwd: Path) -> bool:
    """Resolve container mode against workspace detection.

    Args:
        mode: One of "auto", "enabled", "disabled".
        cwd: Workspace root to check for .devcontainer/.

    Returns:
        True if container execution should be used.

    Raises:
        DevcontainerNotFoundError: If mode is "enabled" but no devcontainer found.
    """
    if mode == "disabled":
        return False
    if mode == "enabled":
        if not has_devcontainer(cwd):
            raise DevcontainerNotFoundError(
                f"Container mode is 'enabled' but no .devcontainer/devcontainer.json "
                f"found in {cwd}"
            )
        return True
    # auto
    return has_devcontainer(cwd)


# --- CLI wrapper ---


def devcontainer_up(workspace_folder: Path, timeout: int = 300) -> None:
    """Start container for workspace. Idempotent — safe to call if already running.

    Args:
        workspace_folder: Path to the workspace (must contain .devcontainer/).
        timeout: Timeout in seconds (default 300s / 5 min).
    """
    logger.info("Starting devcontainer for %s (timeout=%ds)", workspace_folder, timeout)
    try:
        result = subprocess.run(
            ["devcontainer", "up", "--workspace-folder", str(workspace_folder)],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        logger.error(
            "devcontainer up timed out after %ds for %s", timeout, workspace_folder
        )
        raise DevcontainerError(
            f"devcontainer up timed out after {timeout}s for {workspace_folder}"
        )
    if result.returncode != 0:
        logger.error(
            "devcontainer up failed (exit %d) for %s: %s",
            result.returncode, workspace_folder, result.stderr,
        )
        raise DevcontainerError(
            f"devcontainer up failed (exit {result.returncode}) "
            f"for {workspace_folder}\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )


def devcontainer_exec(
    cmd: list[str] | str,
    workspace_folder: Path,
    timeout: int | None = None,
) -> subprocess.CompletedProcess:
    """Run command inside the container.

    Args:
        cmd: Command as list or shell string. If str, wrapped in ["sh", "-c", cmd]
             to support shell syntax (pipes, &&, etc.) needed by test commands.
        workspace_folder: Path to the workspace (must contain .devcontainer/).
        timeout: Optional timeout in seconds.
    """
    if isinstance(cmd, str):
        cmd = ["sh", "-c", cmd]
    args = ["devcontainer", "exec", "--workspace-folder", str(workspace_folder)]
    args += cmd
    kwargs: dict = {"capture_output": True, "text": True, "stdin": subprocess.DEVNULL}
    if timeout is not None:
        kwargs["timeout"] = timeout
    return subprocess.run(args, **kwargs)


def is_container_running(workspace_folder: Path, timeout: int = 30) -> bool:
    """Check if a devcontainer is running for this workspace.

    Args:
        workspace_folder: Path to the workspace.
        timeout: Timeout in seconds (default 30s).

    Returns:
        True if container is running, False if not running or check timed out.
    """
    try:
        result = subprocess.run(
            ["devcontainer", "up", "--workspace-folder", str(workspace_folder),
             "--expect-existing-container"],
            capture_output=True, text=True, timeout=timeout,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        logger.warning(
            "Container status check timed out after %ds for %s",
            timeout, workspace_folder,
        )
        return False


def ensure_container_running(
    workspace_folder: Path,
    timeout_up: int = 300,
    timeout_check: int = 30,
) -> None:
    """Lazy up: start container if not already running. Health check on first start.

    On first successful start, verifies git is available inside the container.
    Raises DevcontainerError if git is not found.

    Args:
        workspace_folder: Path to the workspace.
        timeout_up: Timeout for devcontainer up in seconds.
        timeout_check: Timeout for container status check in seconds.
    """
    logger.debug("Checking container status for %s", workspace_folder)
    if not is_container_running(workspace_folder, timeout=timeout_check):
        devcontainer_up(workspace_folder, timeout=timeout_up)
        # Health check: git must be available for AI agents to commit
        logger.debug("Running git health check in container for %s", workspace_folder)
        result = devcontainer_exec(["git", "--version"], workspace_folder, timeout=15)
        if result.returncode != 0:
            logger.error(
                "git not available inside devcontainer for %s: %s",
                workspace_folder, result.stderr,
            )
            raise DevcontainerError(
                "git is not available inside the devcontainer. "
                "AI agents need git to commit. Add git to your Dockerfile."
            )
