"""Runner abstraction for executing prompts via CLI tools."""

import json
import os
import shlex
import subprocess
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from agent_arborist.home import get_git_root

RunnerType = Literal["claude", "opencode", "gemini"]


def _check_container_running(worktree_path: Path) -> bool:
    """Check if a devcontainer is running for the given worktree."""
    try:
        result = subprocess.run(
            [
                "docker",
                "ps",
                "-q",
                "--filter",
                f"label=devcontainer.local_folder={worktree_path.resolve()}",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return bool(result.stdout.strip())
    except Exception:
        return False


def get_workspace_folder(git_root: Path) -> str:
    """Get workspaceFolder from target project's devcontainer.json.

    Uses the git repo name as the workspace folder container path.
    Example: /workspaces/my-project

    Args:
        git_root: Path to the git repository root.

    Returns:
        The folder path where worktrees are mounted in the container.
        Reads from devcontainer.json if present, otherwise constructs
        using the git repository name.
    """
    devcontainer_json = git_root / ".devcontainer" / "devcontainer.json"
    if devcontainer_json.exists():
        try:
            content = json.loads(devcontainer_json.read_text())
            configured = content.get("workspaceFolder")
            if configured:
                return configured
        except (json.JSONDecodeError, IOError):
            pass

    repo_name = git_root.name if git_root.name else "workspace"
    return f"/workspaces/{repo_name}"


def _wrap_in_container(cmd: list[str], worktree_path: Path) -> list[str]:
    """Wrap command in devcontainer exec if container is running.

    Uses a shell wrapper to ensure the command runs in the workspace directory,
    as devcontainer exec doesn't have a native --workdir flag.

    Workaround based on: https://github.com/devcontainers/cli/issues/703
    """
    if not _check_container_running(worktree_path):
        return cmd

    git_root = get_git_root()
    workspace_folder = get_workspace_folder(git_root or worktree_path.resolve())

    shell_cmd = " ".join(shlex.quote(arg) for arg in cmd)

    return [
        "devcontainer",
        "exec",
        "--workspace-folder",
        str(worktree_path.resolve()),
        "bash",
        "-c",
        f"cd {workspace_folder} && {shell_cmd}",
    ]

# Environment variable names for defaults
ARBORIST_DEFAULT_RUNNER_ENV_VAR = "ARBORIST_DEFAULT_RUNNER"
ARBORIST_DEFAULT_MODEL_ENV_VAR = "ARBORIST_DEFAULT_MODEL"


def _get_default_runner() -> RunnerType:
    """Get default runner from environment or fallback."""
    env_runner = os.environ.get(ARBORIST_DEFAULT_RUNNER_ENV_VAR, "").lower()
    if env_runner in ("claude", "opencode", "gemini"):
        return env_runner  # type: ignore
    return "claude"  # Default to claude


def _get_default_model() -> str | None:
    """Get default model from environment."""
    return os.environ.get(ARBORIST_DEFAULT_MODEL_ENV_VAR) or "sonnet"


# These are functions to allow dynamic resolution from env
def get_default_runner() -> RunnerType:
    """Get the default runner type."""
    return _get_default_runner()


def get_default_model() -> str | None:
    """Get the default model."""
    return _get_default_model()


# For backwards compatibility, expose as a constant that's evaluated at import time
# but prefer using get_default_runner() for dynamic resolution
DEFAULT_RUNNER: RunnerType = _get_default_runner()
DEFAULT_MODEL: str | None = _get_default_model()


@dataclass
class RunResult:
    """Result from running a prompt."""

    success: bool
    output: str
    error: str | None = None
    exit_code: int = 0


class Runner(ABC):
    """Base class for prompt runners."""

    name: str
    command: str

    @abstractmethod
    def run(self, prompt: str, timeout: int = 60, cwd: Path | None = None) -> RunResult:
        """Run a prompt and return the result.

        Args:
            prompt: The prompt to execute
            timeout: Timeout in seconds
            cwd: Working directory for the runner (allows AI to explore files)
        """
        pass

    def is_available(self) -> bool:
        """Check if this runner is available."""
        return shutil.which(self.command) is not None


class ClaudeRunner(Runner):
    """Runner for Claude Code CLI."""

    name = "claude"
    command = "claude"

    def __init__(self, model: str | None = None):
        """Initialize Claude runner.

        Args:
            model: Model to use (e.g., "opus", "sonnet", "haiku" or full model name)
        """
        self.model = model

    def run(self, prompt: str, timeout: int = 60, cwd: Path | None = None) -> RunResult:
        """Run a prompt using Claude CLI.

        If cwd is provided, Claude runs in that directory and can explore files there.
        If a devcontainer is running for that worktree, the command will be wrapped in devcontainer exec.
        """
        path = shutil.which(self.command)
        if not path:
            return RunResult(
                success=False,
                output="",
                error=f"{self.command} not found in PATH",
                exit_code=-1,
            )

        try:
            cmd = [path, "--dangerously-skip-permissions", "-p", prompt]
            if self.model:
                cmd.extend(["--model", self.model])

            # If cwd provided and container running, wrap in devcontainer exec
            using_container = cwd and _check_container_running(cwd)
            if using_container:
                cmd = _wrap_in_container(cmd, cwd)

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=None if using_container else cwd,  # devcontainer exec handles cwd
            )

            return RunResult(
                success=result.returncode == 0,
                output=result.stdout.strip(),
                error=result.stderr.strip() if result.returncode != 0 else None,
                exit_code=result.returncode,
            )

        except subprocess.TimeoutExpired:
            return RunResult(
                success=False,
                output="",
                error=f"Timeout after {timeout} seconds",
                exit_code=-1,
            )
        except Exception as e:
            return RunResult(
                success=False,
                output="",
                error=str(e),
                exit_code=-1,
            )


class OpencodeRunner(Runner):
    """Runner for OpenCode CLI."""

    name = "opencode"
    command = "opencode"

    def __init__(self, model: str | None = None):
        """Initialize OpenCode runner.

        Args:
            model: Model to use in format "provider/model" (e.g., "zai-coding-plan/glm-4.7")
        """
        self.model = model

    def run(self, prompt: str, timeout: int = 60, cwd: Path | None = None) -> RunResult:
        """Run a prompt using OpenCode CLI.

        If cwd is provided, OpenCode runs in that directory and can explore files there.
        If a devcontainer is running for that worktree, the command will be wrapped in devcontainer exec.
        """
        path = shutil.which(self.command)
        if not path:
            return RunResult(
                success=False,
                output="",
                error=f"{self.command} not found in PATH",
                exit_code=-1,
            )

        try:
            # OpenCode uses 'run' subcommand for non-interactive mode
            # TODO: skip permissions can be set in target repo opencode.json file
            cmd = [path, "run"]
            if self.model:
                cmd.extend(["-m", self.model])
            cmd.append(prompt)

            # If cwd provided and container running, wrap in devcontainer exec
            using_container = cwd and _check_container_running(cwd)
            if using_container:
                cmd = _wrap_in_container(cmd, cwd)

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=None if using_container else cwd,  # devcontainer exec handles cwd
            )

            return RunResult(
                success=result.returncode == 0,
                output=result.stdout.strip(),
                error=result.stderr.strip() if result.returncode != 0 else None,
                exit_code=result.returncode,
            )

        except subprocess.TimeoutExpired:
            return RunResult(
                success=False,
                output="",
                error=f"Timeout after {timeout} seconds",
                exit_code=-1,
            )
        except Exception as e:
            return RunResult(
                success=False,
                output="",
                error=str(e),
                exit_code=-1,
            )


class GeminiRunner(Runner):
    """Runner for Gemini CLI."""

    name = "gemini"
    command = "gemini"

    def __init__(self, model: str | None = None):
        """Initialize Gemini runner.

        Args:
            model: Model to use (e.g., "gemini-2.5-flash", "gemini-2.5-pro")
        """
        self.model = model

    def run(self, prompt: str, timeout: int = 60, cwd: Path | None = None) -> RunResult:
        """Run a prompt using Gemini CLI.

        If cwd is provided, Gemini runs in that directory and can explore files there.
        If a devcontainer is running for that worktree, the command will be wrapped in devcontainer exec.
        """
        path = shutil.which(self.command)
        if not path:
            return RunResult(
                success=False,
                output="",
                error=f"{self.command} not found in PATH",
                exit_code=-1,
            )

        try:
            # Gemini CLI uses positional prompt argument
            cmd = [path, "--yolo"]
            if self.model:
                cmd.extend(["-m", self.model])
            cmd.append(prompt)

            # If cwd provided and container running, wrap in devcontainer exec
            using_container = cwd and _check_container_running(cwd)
            if using_container:
                cmd = _wrap_in_container(cmd, cwd)

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=None if using_container else cwd,  # devcontainer exec handles cwd
            )

            return RunResult(
                success=result.returncode == 0,
                output=result.stdout.strip(),
                error=result.stderr.strip() if result.returncode != 0 else None,
                exit_code=result.returncode,
            )

        except subprocess.TimeoutExpired:
            return RunResult(
                success=False,
                output="",
                error=f"Timeout after {timeout} seconds",
                exit_code=-1,
            )
        except Exception as e:
            return RunResult(
                success=False,
                output="",
                error=str(e),
                exit_code=-1,
            )


def get_runner(runner_type: RunnerType | None = None, model: str | None = None) -> Runner:
    """Get a runner instance by type.

    Args:
        runner_type: Type of runner ("claude", "opencode", "gemini").
            If None, uses ARBORIST_RUNNER env var or default.
        model: Model to use (format depends on runner type).
            If None, uses ARBORIST_MODEL env var or default.
            - claude: "opus", "sonnet", "haiku" or full model name
            - gemini: "gemini-2.5-flash", "gemini-2.5-pro", etc.
            - opencode: "provider/model" format, e.g., "zai-coding-plan/glm-4.7"
    """
    runners = {
        "claude": ClaudeRunner,
        "opencode": OpencodeRunner,
        "gemini": GeminiRunner,
    }

    # Use defaults from environment if not provided
    resolved_runner = runner_type or get_default_runner()
    resolved_model = model if model is not None else get_default_model()

    if resolved_runner not in runners:
        raise ValueError(f"Unknown runner type: {resolved_runner}")

    return runners[resolved_runner](model=resolved_model)
