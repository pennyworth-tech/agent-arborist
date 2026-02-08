"""Runner abstraction for executing prompts via CLI tools."""

import os
import subprocess
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

RunnerType = Literal["claude", "opencode", "gemini"]

# Environment variable names for defaults
ARBORIST_DEFAULT_RUNNER_ENV_VAR = "ARBORIST_DEFAULT_RUNNER"
ARBORIST_DEFAULT_MODEL_ENV_VAR = "ARBORIST_DEFAULT_MODEL"

# Default runners/models for different purposes
# Task execution: opencode with Cerebras (fast, good for implementation)
TASK_DEFAULT_RUNNER: RunnerType = "opencode"
TASK_DEFAULT_MODEL: str = "cerebras/zai-glm-4.7"

# DAG building (spec analysis): claude with opus (best reasoning)
DAG_DEFAULT_RUNNER: RunnerType = "claude"
DAG_DEFAULT_MODEL: str = "opus"


def _get_default_runner() -> RunnerType:
    """Get default runner from environment or fallback to task default."""
    env_runner = os.environ.get(ARBORIST_DEFAULT_RUNNER_ENV_VAR, "").lower()
    if env_runner in ("claude", "opencode", "gemini"):
        return env_runner  # type: ignore
    return TASK_DEFAULT_RUNNER


def _get_default_model() -> str | None:
    """Get default model from environment or fallback to task default."""
    return os.environ.get(ARBORIST_DEFAULT_MODEL_ENV_VAR) or TASK_DEFAULT_MODEL


# These are functions to allow dynamic resolution from env
def get_default_runner() -> RunnerType:
    """Get the default runner type for task execution."""
    return _get_default_runner()


def get_default_model() -> str | None:
    """Get the default model for task execution."""
    return _get_default_model()


def get_dag_runner() -> RunnerType:
    """Get the default runner type for DAG building."""
    return DAG_DEFAULT_RUNNER


def get_dag_model() -> str:
    """Get the default model for DAG building."""
    return DAG_DEFAULT_MODEL


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


def _execute_command(
    cmd: list[str],
    timeout: int,
    cwd: Path | None = None,
    container_cmd_prefix: list[str] | None = None,
) -> RunResult:
    """Execute a command and return standardized result.

    This centralizes the common subprocess execution logic used by all runners.

    Args:
        cmd: Command and arguments to execute
        timeout: Timeout in seconds
        cwd: Working directory for execution
        container_cmd_prefix: Optional prefix for container execution (e.g., ["devcontainer", "exec", ...])
                             If provided, prepends this to cmd and cwd is handled by container

    Returns:
        RunResult with success status, output, and error details
    """
    # Apply container prefix if provided
    if container_cmd_prefix:
        cmd = container_cmd_prefix + cmd
        # Container sets working directory, don't pass cwd to subprocess
        cwd = None

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
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


class Runner(ABC):
    """Base class for prompt runners."""

    name: str
    command: str

    @abstractmethod
    def run(
        self,
        prompt: str,
        timeout: int = 60,
        cwd: Path | None = None,
        container_cmd_prefix: list[str] | None = None,
    ) -> RunResult:
        """Run a prompt and return the result.

        Args:
            prompt: The prompt to execute
            timeout: Timeout in seconds
            cwd: Working directory for the runner (allows AI to explore files)
            container_cmd_prefix: Optional prefix for container execution
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

    def run(
        self,
        prompt: str,
        timeout: int = 60,
        cwd: Path | None = None,
        container_cmd_prefix: list[str] | None = None,
    ) -> RunResult:
        """Run a prompt using Claude CLI.

        If cwd is provided, Claude runs in that directory and can explore files there.
        """
        cmd = [self.command, "--dangerously-skip-permissions", "-p", prompt]
        if self.model:
            cmd.extend(["--model", self.model])

        return _execute_command(cmd, timeout, cwd, container_cmd_prefix)


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

    def run(
        self,
        prompt: str,
        timeout: int = 60,
        cwd: Path | None = None,
        container_cmd_prefix: list[str] | None = None,
    ) -> RunResult:
        """Run a prompt using OpenCode CLI."""
        # OpenCode uses 'run' subcommand for non-interactive mode
        # TODO: skip permissions can be set in target repo opencode.json file
        cmd = [self.command, "run"]
        if self.model:
            cmd.extend(["-m", self.model])
        cmd.append(prompt)

        return _execute_command(cmd, timeout, cwd, container_cmd_prefix)


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

    def run(
        self,
        prompt: str,
        timeout: int = 60,
        cwd: Path | None = None,
        container_cmd_prefix: list[str] | None = None,
    ) -> RunResult:
        """Run a prompt using Gemini CLI."""
        # Gemini CLI uses positional prompt argument
        cmd = [self.command, "--yolo"]
        if self.model:
            cmd.extend(["-m", self.model])
        cmd.append(prompt)

        return _execute_command(cmd, timeout, cwd, container_cmd_prefix)


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
