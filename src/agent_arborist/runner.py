"""Runner abstraction for executing prompts via CLI tools."""

import subprocess
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass
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
    def run(self, prompt: str, timeout: int = 60) -> RunResult:
        """Run a prompt and return the result."""
        pass

    def is_available(self) -> bool:
        """Check if this runner is available."""
        return shutil.which(self.command) is not None


class ClaudeRunner(Runner):
    """Runner for Claude Code CLI."""

    name = "claude"
    command = "claude"

    def run(self, prompt: str, timeout: int = 60) -> RunResult:
        """Run a prompt using Claude CLI."""
        path = shutil.which(self.command)
        if not path:
            return RunResult(
                success=False,
                output="",
                error=f"{self.command} not found in PATH",
                exit_code=-1,
            )

        try:
            result = subprocess.run(
                [path, "-p", prompt],
                capture_output=True,
                text=True,
                timeout=timeout,
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

    def run(self, prompt: str, timeout: int = 60) -> RunResult:
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
            result = subprocess.run(
                [path, "run", prompt],
                capture_output=True,
                text=True,
                timeout=timeout,
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

    def run(self, prompt: str, timeout: int = 60) -> RunResult:
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
            result = subprocess.run(
                [path, prompt],
                capture_output=True,
                text=True,
                timeout=timeout,
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


def get_runner(runner_type: RunnerType = DEFAULT_RUNNER) -> Runner:
    """Get a runner instance by type."""
    runners = {
        "claude": ClaudeRunner,
        "opencode": OpencodeRunner,
        "gemini": GeminiRunner,
    }

    if runner_type not in runners:
        raise ValueError(f"Unknown runner type: {runner_type}")

    return runners[runner_type]()
