"""DevContainer detection and execution for target projects.

This module detects if the target project has a .devcontainer/ and
wraps runner execution in devcontainer commands.

Arborist does NOT provide a devcontainer - it uses the target's.
"""

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from agent_arborist.home import get_git_root


class ContainerMode(Enum):
    """Container execution mode for DAG steps."""

    AUTO = "auto"  # Use devcontainer if target has .devcontainer/
    ENABLED = "enabled"  # Require devcontainer, fail if not present
    DISABLED = "disabled"  # Never use devcontainer


@dataclass
class ContainerConfig:
    """Configuration for DevContainer execution."""

    # Container mode
    mode: ContainerMode = ContainerMode.AUTO

    # Timeout for devcontainer up (seconds)
    up_timeout: int = 300

    # Timeout for devcontainer exec (seconds)
    exec_timeout: int = 3600


@dataclass
class ContainerResult:
    """Result from a container operation."""

    success: bool
    output: str
    error: str | None = None
    exit_code: int = 0


@dataclass
class ValidationStatus:
    """Result of devcontainer configuration validation."""

    valid: bool
    errors: list[str]
    warnings: list[str]


def validate_devcontainer_config(worktree_path: Path) -> ValidationStatus:
    """Validate devcontainer.json and Dockerfile for workspace consistency.

    Checks for common misconfigurations that can cause container startup failures,
    such as workspaceFolder mismatches with the actual mount point.

    Note: If workspaceFolder is not set in devcontainer.json, the devcontainer CLI
    will automatically mount to /workspaces/<folder-name>. This is the recommended
    approach - remove workspaceFolder and WORKDIR to let the CLI manage it.

    Args:
        worktree_path: Path to the worktree directory.

    Returns:
        ValidationStatus with validation results.
    """
    errors: list[str] = []
    warnings: list[str] = []

    worktree_path = worktree_path.resolve()
    devcontainer_dir = worktree_path / ".devcontainer"

    # Check devcontainer.json exists
    devcontainer_json = devcontainer_dir / "devcontainer.json"
    if not devcontainer_json.exists():
        return ValidationStatus(valid=True, errors=[], warnings=["No devcontainer.json found"])

    # Read devcontainer.json
    try:
        dc_config = json.loads(devcontainer_json.read_text())
    except Exception as e:
        errors.append(f"Could not parse devcontainer.json: {e}")
        return ValidationStatus(valid=False, errors=errors, warnings=warnings)

    # Check workspaceFolder
    workspace_folder = dc_config.get("workspaceFolder")

    # Check Dockerfile
    dockerfile = devcontainer_dir / "Dockerfile"
    if dockerfile.exists():
        dockerfile_content = dockerfile.read_text()
        workdir_match = None

        for line in dockerfile_content.split('\n'):
            line = line.strip()
            if line.lower().startswith('workdir'):
                workdir_match = line.split(maxsplit=1)[1] if len(line.split()) > 1 else None
                break

        # If workspaceFolder is set, Dockerfile WORKDIR must match it
        if workdir_match and workspace_folder:
            if workdir_match.replace('\\', '') != workspace_folder:
                errors.append(
                    f"Dockerfile WORKDIR '{workdir_match}' does not match "
                    f"workspaceFolder '{workspace_folder}' in devcontainer.json. "
                    f"Both must be set to the same path to avoid OCI runtime errors."
                )
                return ValidationStatus(valid=False, errors=errors, warnings=warnings)

        # If workspaceFolder is not set but WORKDIR is, warn about the mismatch
        if workdir_match and not workspace_folder:
            worktree_name = worktree_path.name
            expected_folder = f"/workspaces/{worktree_name}"
            if workdir_match.replace('\\', '') != expected_folder:
                warnings.append(
                    f"Dockerfile has WORKDIR '{workdir_match}' but workspaceFolder is not set in devcontainer.json. "
                    f"Devcontainer CLI will mount to '{expected_folder}'. "
                    f"Remove WORKDIR from Dockerfile to let CLI manage the workspace mount point."
                )

    return ValidationStatus(valid=len(errors) == 0, errors=errors, warnings=warnings)


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


class DevContainerRunner:
    """Wraps runner execution in the target project's devcontainer.

    Each worktree gets its own container instance using the
    target project's .devcontainer/ configuration.
    """

    def __init__(self, config: ContainerConfig | None = None):
        self.config = config or ContainerConfig()

    def container_up(self, worktree_path: Path) -> ContainerResult:
        """Start devcontainer for a worktree.

        Uses the target project's .devcontainer/ configuration.
        Container is named based on worktree folder.

        Args:
            worktree_path: Absolute path to the worktree directory.

        Returns:
            ContainerResult with success/failure and output.
        """
        worktree_path = worktree_path.resolve()

        # Ensure worktree has access to .devcontainer (symlink if needed)
        self._ensure_devcontainer_accessible(worktree_path)

        # Validate devcontainer configuration for potential issues
        validation = validate_devcontainer_config(worktree_path)
        if validation.errors:
            error_msg = "\n".join(validation.errors)
            return ContainerResult(
                success=False,
                output="",
                error=f"Devcontainer validation failed:\n{error_msg}",
                exit_code=-1,
            )
        if validation.warnings:
            for warning in validation.warnings:
                print(f"[WARNING] {warning}", file=sys.stderr)

        cmd = [
            "devcontainer",
            "up",
            "--workspace-folder",
            str(worktree_path),
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.config.up_timeout,
            )

            if result.returncode != 0:
                return ContainerResult(
                    success=False,
                    output=result.stdout,
                    error=result.stderr,
                    exit_code=result.returncode,
                )

            # Wait for container to be fully ready
            readiness_result = self.wait_for_container_ready(worktree_path, timeout=30)
            if not readiness_result.success:
                return readiness_result

            return ContainerResult(
                success=True,
                output=result.stdout + "\n" + readiness_result.output,
                exit_code=0,
            )

        except subprocess.TimeoutExpired:
            return ContainerResult(
                success=False,
                output="",
                error=f"Container startup timed out after {self.config.up_timeout}s",
                exit_code=-1,
            )
        except Exception as e:
            return ContainerResult(
                success=False,
                output="",
                error=str(e),
                exit_code=-1,
            )

    def exec(
        self,
        worktree_path: Path,
        command: list[str],
        env: dict[str, str] | None = None,
        timeout: int | None = None,
    ) -> ContainerResult:
        """Execute command in running devcontainer.

        Args:
            worktree_path: Path to the worktree.
            command: Command and arguments to execute.
            env: Additional environment variables.
            timeout: Command timeout in seconds.

        Returns:
            ContainerResult with command output.
        """
        worktree_path = worktree_path.resolve()
        timeout = timeout or self.config.exec_timeout

        cmd = [
            "devcontainer",
            "exec",
            "--workspace-folder",
            str(worktree_path),
        ]

        if env:
            for key, value in env.items():
                cmd.extend(["--remote-env", f"{key}={value}"])

        cmd.extend(command)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            return ContainerResult(
                success=result.returncode == 0,
                output=result.stdout,
                error=result.stderr if result.returncode != 0 else None,
                exit_code=result.returncode,
            )

        except subprocess.TimeoutExpired:
            return ContainerResult(
                success=False,
                output="",
                error=f"Command timed out after {timeout}s",
                exit_code=-1,
            )
        except Exception as e:
            return ContainerResult(
                success=False,
                output="",
                error=str(e),
                exit_code=-1,
            )

    def container_down(self, worktree_path: Path) -> ContainerResult:
        """Stop devcontainer for a worktree.

        Args:
            worktree_path: Path to the worktree.

        Returns:
            ContainerResult with success/failure.
        """
        worktree_path = worktree_path.resolve()

        # Find container by devcontainer label
        find_cmd = [
            "docker",
            "ps",
            "-q",
            "--filter",
            f"label=devcontainer.local_folder={worktree_path}",
        ]

        try:
            find_result = subprocess.run(find_cmd, capture_output=True, text=True)
            container_id = find_result.stdout.strip()

            if not container_id:
                return ContainerResult(
                    success=True,
                    output="No container found (already stopped)",
                )

            stop_result = subprocess.run(
                ["docker", "stop", container_id],
                capture_output=True,
                text=True,
            )

            return ContainerResult(
                success=stop_result.returncode == 0,
                output=(
                    f"Stopped container {container_id}"
                    if stop_result.returncode == 0
                    else stop_result.stdout
                ),
                error=stop_result.stderr if stop_result.returncode != 0 else None,
                exit_code=stop_result.returncode,
            )

        except Exception as e:
            return ContainerResult(
                success=False,
                output="",
                error=str(e),
                exit_code=-1,
            )

    def wait_for_container_ready(
        self,
        worktree_path: Path,
        timeout: int = 30,
        interval: float = 1.0,
    ) -> ContainerResult:
        """Wait for container to be fully ready after startup.

        Args:
            worktree_path: Path to the worktree.
            timeout: Maximum seconds to wait.
            interval: Seconds between checks.

        Returns:
            ContainerResult indicating readiness.
        """
        import time

        start_time = time.time()
        worktree_path = worktree_path.resolve()

        while time.time() - start_time < timeout:
            # Check if container is running
            check_cmd = [
                "docker",
                "ps",
                "-q",
                "--filter",
                f"label=devcontainer.local_folder={worktree_path}",
            ]

            try:
                result = subprocess.run(
                    check_cmd, capture_output=True, text=True, timeout=5
                )
                if result.stdout.strip():
                    # Container found, test if it's responsive
                    test_result = self.exec(worktree_path, ["echo", "ready"], timeout=5)
                    if test_result.success:
                        return ContainerResult(
                            success=True,
                            output=f"Container ready after {time.time() - start_time:.1f}s",
                        )
            except Exception:
                pass

            time.sleep(interval)

        return ContainerResult(
            success=False,
            output="",
            error=f"Container not ready after {timeout}s",
            exit_code=-1,
        )

    def _ensure_devcontainer_accessible(self, worktree_path: Path) -> None:
        """Ensure worktree can access .devcontainer config.

        Git worktrees share .git with main repo, so .devcontainer
        should be accessible. If not, create symlink.

        Args:
            worktree_path: Path to the worktree.
        """
        target = worktree_path / ".devcontainer"
        if target.exists():
            return

        # Find repo root's .devcontainer
        git_root = get_git_root()
        source = git_root / ".devcontainer"

        if source.exists() and source != target:
            target.symlink_to(source)


# ============================================================
# SHELL COMMAND GENERATORS (for DAG steps)
# ============================================================


def devcontainer_up_command() -> str:
    """Generate shell command for container-up step.

    Uses arborist CLI to ensure proper initialization (symlink creation, etc).
    Task ID will be injected by DAG builder.
    """
    return "arborist task container-up"


def devcontainer_exec_command(
    command: str,
    worktree_env_var: str = "${ARBORIST_WORKTREE}",
) -> str:
    """Generate shell command wrapping a command in devcontainer exec."""
    return f'devcontainer exec --workspace-folder "{worktree_env_var}" {command}'


def devcontainer_down_command() -> str:
    """Generate shell command for container-down step.

    Uses arborist CLI for proper cleanup.
    Task ID will be injected by DAG builder.
    """
    return "arborist task container-down"
