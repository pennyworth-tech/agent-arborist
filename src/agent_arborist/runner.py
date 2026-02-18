"""Runner abstraction for executing prompts via CLI tools."""

import logging
import subprocess
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

RunnerType = Literal["claude", "opencode", "gemini"]

# DAG building (spec analysis): claude with opus (best reasoning)
DAG_DEFAULT_RUNNER: RunnerType = "claude"
DAG_DEFAULT_MODEL: str = "opus"


# Conversational filler patterns to skip when extracting commit summaries
_FILLER_PREFIXES = (
    "perfect", "excellent", "great", "done", "complete", "success",
    "i've", "i have", "let me", "here's", "here is", "now let",
    "task t", "t0", "files changed", "**t", "**task",
)


def _extract_commit_summary(output: str) -> str | None:
    """Extract a meaningful commit summary from AI output.

    Skips conversational filler and looks for substantive content
    that describes what was actually done.

    Args:
        output: Raw AI output text

    Returns:
        A meaningful summary line, or None if not found
    """
    lines = output.strip().split("\n")

    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Skip markdown headers
        if line.startswith("#"):
            continue
        # Skip conversational filler
        lower = line.lower()
        if any(lower.startswith(prefix) for prefix in _FILLER_PREFIXES):
            continue
        # Skip lines that are just task references
        if lower.startswith("t0") and len(line) < 20:
            continue
        # Found a substantive line
        return line[:500]

    return None


def get_dag_runner() -> RunnerType:
    """Get the default runner type for DAG building."""
    return DAG_DEFAULT_RUNNER


def get_dag_model() -> str:
    """Get the default model for DAG building."""
    return DAG_DEFAULT_MODEL


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
    container_workspace: Path | None = None,
    container_up_timeout: int | None = None,
    container_check_timeout: int | None = None,
) -> RunResult:
    """Execute a command and return standardized result.

    This centralizes the common subprocess execution logic used by all runners.

    Args:
        cmd: Command and arguments to execute
        timeout: Timeout in seconds
        cwd: Working directory for execution
        container_workspace: If set, run inside devcontainer for this workspace
        container_up_timeout: Timeout for devcontainer up (None = use config default)
        container_check_timeout: Timeout for container check (None = use config default)

    Returns:
        RunResult with success status, output, and error details
    """
    logger.info("Running %s (timeout=%ds)", cmd[0], timeout)
    logger.debug("Full command: %s", cmd)

    if container_workspace:
        from agent_arborist.devcontainer import ensure_container_running, devcontainer_exec
        kwargs = {}
        if container_up_timeout is not None:
            kwargs["timeout_up"] = container_up_timeout
        if container_check_timeout is not None:
            kwargs["timeout_check"] = container_check_timeout
        ensure_container_running(container_workspace, **kwargs)
        result = devcontainer_exec(cmd, container_workspace, timeout=timeout)
    else:
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
            )
        except subprocess.TimeoutExpired:
            logger.warning("Command timed out after %ds: %s", timeout, cmd[0])
            return RunResult(
                success=False,
                output="",
                error=f"Timeout after {timeout} seconds",
                exit_code=-1,
            )
        except Exception as e:
            logger.warning("Command error: %s", e)
            return RunResult(
                success=False,
                output="",
                error=str(e),
                exit_code=-1,
            )

    logger.debug("Command output length: %d chars", len(result.stdout))
    return RunResult(
        success=result.returncode == 0,
        output=result.stdout.strip(),
        error=result.stderr.strip() if result.returncode != 0 else None,
        exit_code=result.returncode,
    )


class Runner(ABC):
    """Base class for prompt runners."""

    name: str
    command: str

    @abstractmethod
    def run(
        self,
        prompt: str,
        timeout: int = 600,
        cwd: Path | None = None,
        container_workspace: Path | None = None,
        container_up_timeout: int | None = None,
        container_check_timeout: int | None = None,
    ) -> RunResult:
        """Run a prompt and return the result.

        Args:
            prompt: The prompt to execute
            timeout: Timeout in seconds
            cwd: Working directory for the runner (allows AI to explore files)
            container_workspace: Workspace path for devcontainer execution
            container_up_timeout: Timeout for devcontainer up (None = config default)
            container_check_timeout: Timeout for container check (None = config default)
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
        timeout: int = 600,
        cwd: Path | None = None,
        container_workspace: Path | None = None,
        container_up_timeout: int | None = None,
        container_check_timeout: int | None = None,
    ) -> RunResult:
        """Run a prompt using Claude CLI.

        If cwd is provided, Claude runs in that directory and can explore files there.
        """
        cmd = [self.command, "--dangerously-skip-permissions", "-p", prompt]
        if self.model:
            cmd.extend(["--model", self.model])

        return _execute_command(
            cmd, timeout, cwd, container_workspace,
            container_up_timeout, container_check_timeout,
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

    def run(
        self,
        prompt: str,
        timeout: int = 600,
        cwd: Path | None = None,
        container_workspace: Path | None = None,
        container_up_timeout: int | None = None,
        container_check_timeout: int | None = None,
    ) -> RunResult:
        """Run a prompt using OpenCode CLI."""
        # OpenCode uses 'run' subcommand for non-interactive mode
        # TODO: skip permissions can be set in target repo opencode.json file
        cmd = [self.command, "run"]
        if self.model:
            cmd.extend(["-m", self.model])
        cmd.append(prompt)

        return _execute_command(
            cmd, timeout, cwd, container_workspace,
            container_up_timeout, container_check_timeout,
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

    def run(
        self,
        prompt: str,
        timeout: int = 600,
        cwd: Path | None = None,
        container_workspace: Path | None = None,
        container_up_timeout: int | None = None,
        container_check_timeout: int | None = None,
    ) -> RunResult:
        """Run a prompt using Gemini CLI."""
        # Gemini CLI uses positional prompt argument
        cmd = [self.command, "--yolo"]
        if self.model:
            cmd.extend(["-m", self.model])
        cmd.append(prompt)

        return _execute_command(
            cmd, timeout, cwd, container_workspace,
            container_up_timeout, container_check_timeout,
        )


def get_runner(runner_type: RunnerType, model: str | None = None) -> Runner:
    """Get a runner instance by type.

    Args:
        runner_type: Type of runner ("claude", "opencode", "gemini").
        model: Model to use (format depends on runner type).
            - claude: "opus", "sonnet", "haiku" or full model name
            - gemini: "gemini-2.5-flash", "gemini-2.5-pro", etc.
            - opencode: "provider/model" format, e.g., "zai-coding-plan/glm-4.7"
    """
    runners = {
        "claude": ClaudeRunner,
        "opencode": OpencodeRunner,
        "gemini": GeminiRunner,
    }

    if runner_type not in runners:
        raise ValueError(f"Unknown runner type: {runner_type}")

    return runners[runner_type](model=model)


@dataclass
class AITaskResult:
    """Result from running an AI task."""

    success: bool
    output: str = ""
    error: str | None = None
    summary: str | None = None
    duration_seconds: float | None = None


def run_ai_task(
    prompt: str,
    runner: RunnerType | None = None,
    model: str | None = None,
    cwd: Path | None = None,
    timeout: int = 1800,
    container_workspace: Path | None = None,
    container_up_timeout: int | None = None,
    container_check_timeout: int | None = None,
) -> AITaskResult:
    """Run an AI task using the specified runner.

    This is the main entry point for executing AI tasks.

    Args:
        prompt: The task prompt to execute
        runner: Runner type to use (claude, opencode, gemini)
        model: Model to use
        cwd: Working directory for the AI to explore
        timeout: Timeout in seconds
        container_workspace: If set, run inside devcontainer for this workspace
        container_up_timeout: Timeout for devcontainer up (None = config default)
        container_check_timeout: Timeout for container check (None = config default)

    Returns:
        AITaskResult with success status and details
    """
    import time

    start_time = time.time()

    try:
        runner_instance = get_runner(runner, model)

        result = runner_instance.run(
            prompt=prompt,
            timeout=timeout,
            cwd=cwd,
            container_workspace=container_workspace,
            container_up_timeout=container_up_timeout,
            container_check_timeout=container_check_timeout,
        )

        duration = time.time() - start_time

        if result.success:
            # Extract a meaningful summary, skipping conversational filler
            summary = _extract_commit_summary(result.output)

            return AITaskResult(
                success=True,
                output=result.output,
                summary=summary,
                duration_seconds=duration,
            )
        else:
            return AITaskResult(
                success=False,
                output=result.output,
                error=result.error,
                duration_seconds=duration,
            )

    except Exception as e:
        duration = time.time() - start_time
        return AITaskResult(
            success=False,
            error=str(e),
            duration_seconds=duration,
        )
