"""Runner abstraction for executing prompts via CLI tools."""

import subprocess
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

RunnerType = Literal["claude", "opencode", "gemini"]

DEFAULT_RUNNER: RunnerType = "claude"


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
            cmd = [path, "-p", prompt]
            if self.model:
                cmd.extend(["--model", self.model])

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
        """Run a prompt using OpenCode CLI."""
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
            cmd = [path, "run"]
            if self.model:
                cmd.extend(["-m", self.model])
            cmd.append(prompt)

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
        """Run a prompt using Gemini CLI."""
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
            cmd = [path]
            if self.model:
                cmd.extend(["-m", self.model])
            cmd.append(prompt)

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


def get_runner(runner_type: RunnerType = DEFAULT_RUNNER, model: str | None = None) -> Runner:
    """Get a runner instance by type.

    Args:
        runner_type: Type of runner ("claude", "opencode", "gemini")
        model: Model to use (format depends on runner type)
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
