"""Step executors for hook system.

Each step type has an executor that knows how to run it and return
appropriate results.
"""

from __future__ import annotations

import importlib
import json
import logging
import re
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent_arborist.config import StepDefinition
from agent_arborist.hooks.base import CustomStep, StepContext
from agent_arborist.hooks.prompt_loader import PromptLoader, substitute_variables
from agent_arborist.step_results import (
    CustomStepResult,
    LLMEvalResult,
    QualityCheckResult,
    ShellStepResult,
    StepResultBase,
)

if TYPE_CHECKING:
    from agent_arborist.config import ArboristConfig

logger = logging.getLogger(__name__)


class StepExecutionError(Exception):
    """Raised when step execution fails."""

    pass


@dataclass
class ExecutorContext:
    """Context provided to step executors.

    Contains all information needed to execute a step.
    """

    step_ctx: StepContext
    step_def: StepDefinition
    arborist_config: "ArboristConfig"
    prompts_dir: Path


class StepExecutor(ABC):
    """Base class for step executors."""

    @abstractmethod
    def execute(self, ctx: ExecutorContext) -> StepResultBase:
        """Execute the step and return result.

        Args:
            ctx: Execution context with step config and environment info

        Returns:
            Appropriate StepResult subclass
        """
        pass


class ShellStepExecutor(StepExecutor):
    """Executor for shell command steps."""

    def execute(self, ctx: ExecutorContext) -> ShellStepResult:
        """Execute shell command and return result."""
        start_time = time.time()
        step_def = ctx.step_def

        # Substitute variables in command
        command = step_def.command or ""
        command = substitute_variables(command, ctx.step_ctx)

        # Determine working directory
        if step_def.working_dir:
            cwd = Path(substitute_variables(step_def.working_dir, ctx.step_ctx))
        elif ctx.step_ctx.worktree_path:
            cwd = ctx.step_ctx.worktree_path
        else:
            cwd = None

        # Build environment
        env = dict(step_def.env) if step_def.env else {}
        # Substitute variables in env values
        for key, value in env.items():
            env[key] = substitute_variables(value, ctx.step_ctx)

        logger.debug(f"Executing shell command: {command}")
        logger.debug(f"Working directory: {cwd}")

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=step_def.timeout,
                cwd=cwd,
                env={**dict(subprocess.os.environ), **env} if env else None,
            )

            duration = time.time() - start_time
            success = result.returncode == 0

            return ShellStepResult(
                success=success,
                command=command,
                return_code=result.returncode,
                stdout=result.stdout.strip(),
                stderr=result.stderr.strip(),
                duration_seconds=duration,
                error=result.stderr.strip() if not success else None,
            )

        except subprocess.TimeoutExpired:
            duration = time.time() - start_time
            return ShellStepResult(
                success=False,
                command=command,
                return_code=-1,
                stdout="",
                stderr="",
                duration_seconds=duration,
                error=f"Command timed out after {step_def.timeout}s",
            )

        except Exception as e:
            duration = time.time() - start_time
            return ShellStepResult(
                success=False,
                command=command,
                return_code=-1,
                stdout="",
                stderr="",
                duration_seconds=duration,
                error=str(e),
            )


class LLMEvalStepExecutor(StepExecutor):
    """Executor for LLM evaluation steps.

    Runs an LLM with a prompt and extracts a score and summary.
    The LLM is expected to return JSON with 'score' and 'summary' fields.
    """

    def execute(self, ctx: ExecutorContext) -> LLMEvalResult:
        """Execute LLM evaluation and return result."""
        start_time = time.time()
        step_def = ctx.step_def

        # Load prompt
        loader = PromptLoader(ctx.prompts_dir)
        try:
            prompt_template = loader.load({
                "prompt": step_def.prompt,
                "prompt_file": step_def.prompt_file,
            })
        except Exception as e:
            return LLMEvalResult(
                success=False,
                error=f"Failed to load prompt: {e}",
                duration_seconds=time.time() - start_time,
            )

        # Substitute variables in prompt
        prompt = substitute_variables(prompt_template, ctx.step_ctx)

        # Add JSON output instruction if not present
        if "json" not in prompt.lower():
            prompt += """

Please respond with JSON in this exact format:
{
  "score": <float between 0.0 and 1.0>,
  "summary": "<brief summary of evaluation>"
}"""

        # Determine runner and model
        runner = step_def.runner or ctx.arborist_config.defaults.runner or "claude"
        model = step_def.model or ctx.arborist_config.defaults.model

        # Build command based on runner
        try:
            output, error = self._run_llm(
                runner=runner,
                model=model,
                prompt=prompt,
                timeout=step_def.timeout,
                cwd=ctx.step_ctx.worktree_path,
            )
        except Exception as e:
            return LLMEvalResult(
                success=False,
                error=str(e),
                runner=runner,
                model=model,
                duration_seconds=time.time() - start_time,
            )

        duration = time.time() - start_time

        if error:
            return LLMEvalResult(
                success=False,
                error=error,
                raw_response=output,
                runner=runner,
                model=model,
                duration_seconds=duration,
            )

        # Parse response
        try:
            result = self._parse_response(output)
            return LLMEvalResult(
                success=True,
                score=result.get("score", 0.0),
                summary=result.get("summary", ""),
                raw_response=output,
                runner=runner,
                model=model,
                duration_seconds=duration,
            )
        except Exception as e:
            return LLMEvalResult(
                success=False,
                error=f"Failed to parse LLM response: {e}",
                raw_response=output,
                runner=runner,
                model=model,
                duration_seconds=duration,
            )

    def _run_llm(
        self,
        runner: str,
        model: str | None,
        prompt: str,
        timeout: int,
        cwd: Path | None,
    ) -> tuple[str, str | None]:
        """Run LLM and return (output, error).

        Args:
            runner: Runner name (claude, opencode, gemini)
            model: Model name or alias
            prompt: Prompt to send
            timeout: Timeout in seconds
            cwd: Working directory

        Returns:
            Tuple of (output_text, error_message_or_none)
        """
        if runner == "claude":
            cmd = ["claude", "--print", "--output-format", "text"]
            if model:
                cmd.extend(["--model", model])
            cmd.extend(["-p", prompt])
        elif runner == "opencode":
            cmd = ["opencode", "run"]
            if model:
                cmd.extend(["--model", model])
            cmd.append(prompt)
        elif runner == "gemini":
            cmd = ["gemini", "--print"]
            if model:
                cmd.extend(["--model", model])
            cmd.extend(["-p", prompt])
        else:
            return "", f"Unknown runner: {runner}"

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
            )

            if result.returncode != 0:
                return result.stdout, result.stderr or f"Command failed with exit code {result.returncode}"

            return result.stdout, None

        except subprocess.TimeoutExpired:
            return "", f"LLM call timed out after {timeout}s"
        except FileNotFoundError:
            return "", f"Runner '{runner}' not found. Ensure it is installed and in PATH."
        except Exception as e:
            return "", str(e)

    def _parse_response(self, output: str) -> dict[str, Any]:
        """Parse LLM response to extract score and summary.

        Handles various response formats:
        - Pure JSON
        - JSON in markdown code blocks
        - Messy JSON mixed with text

        Args:
            output: Raw LLM output

        Returns:
            Dict with 'score' and 'summary' keys
        """
        # Try to find JSON in the response
        # First, try markdown code block
        json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", output, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # Try to find raw JSON object
        json_match = re.search(r"\{[^{}]*\"score\"[^{}]*\}", output, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except json.JSONDecodeError:
                pass

        # Try the entire output as JSON
        try:
            return json.loads(output.strip())
        except json.JSONDecodeError:
            pass

        # Last resort: extract score and summary from text
        score = 0.0
        summary = output[:200].strip()

        # Look for score patterns
        score_match = re.search(r"score[:\s]+(\d+(?:\.\d+)?)", output, re.IGNORECASE)
        if score_match:
            try:
                score = float(score_match.group(1))
                # Normalize to 0-1 if necessary
                if score > 1:
                    score = score / 100 if score <= 100 else score / 1000
            except ValueError:
                pass

        return {"score": score, "summary": summary}


class QualityCheckStepExecutor(StepExecutor):
    """Executor for quality check steps.

    Runs a command and extracts a numeric score from the output.
    """

    def execute(self, ctx: ExecutorContext) -> QualityCheckResult:
        """Execute quality check and return result."""
        start_time = time.time()
        step_def = ctx.step_def

        # First run the shell command
        shell_executor = ShellStepExecutor()
        shell_result = shell_executor.execute(ctx)

        duration = time.time() - start_time

        # Extract score from output
        output = shell_result.stdout + "\n" + shell_result.stderr
        score = self._extract_score(output, step_def.score_extraction)

        # Check threshold
        min_score = step_def.min_score
        passed = True
        if min_score is not None:
            passed = score >= min_score

        # Determine overall success:
        # - Shell command must succeed
        # - If fail_on_threshold is True, score must meet threshold
        # - If fail_on_threshold is False, we still track passed but don't fail
        success = shell_result.success
        if step_def.fail_on_threshold and not passed:
            success = False

        error = shell_result.error
        if not passed and step_def.fail_on_threshold:
            error = f"Score {score} below threshold {min_score}"

        return QualityCheckResult(
            success=success,
            score=score,
            min_score=min_score,
            passed=passed,
            command=shell_result.command,
            return_code=shell_result.return_code,
            output=output,
            duration_seconds=duration,
            error=error,
        )

    def _extract_score(
        self, output: str, extraction_config: dict[str, Any] | None
    ) -> float:
        """Extract numeric score from command output.

        Args:
            output: Command output text
            extraction_config: Optional extraction configuration:
                - pattern: regex with capture group for score
                - format: "percentage" (0-100), "decimal" (0-1), "raw"

        Returns:
            Extracted score as float (normalized to 0-1)
        """
        if extraction_config:
            pattern = extraction_config.get("pattern")
            if pattern:
                match = re.search(pattern, output)
                if match:
                    try:
                        score = float(match.group(1))
                        fmt = extraction_config.get("format", "raw")
                        if fmt == "percentage":
                            return score / 100
                        return score
                    except (ValueError, IndexError):
                        pass

        # Default extraction patterns
        # Try percentage format first (e.g., "Coverage: 85%")
        pct_match = re.search(r"(\d+(?:\.\d+)?)\s*%", output)
        if pct_match:
            return float(pct_match.group(1)) / 100

        # Try fraction format (e.g., "Passed: 8/10")
        frac_match = re.search(r"(\d+)\s*/\s*(\d+)", output)
        if frac_match:
            num = float(frac_match.group(1))
            denom = float(frac_match.group(2))
            if denom > 0:
                return num / denom

        # Try decimal format (e.g., "Score: 0.85")
        dec_match = re.search(r"score[:\s]+(\d+\.\d+)", output, re.IGNORECASE)
        if dec_match:
            return float(dec_match.group(1))

        # Default to 0 if no score found
        return 0.0


class CustomStepExecutor(StepExecutor):
    """Executor for custom Python steps.

    Dynamically loads and executes a Python class that implements CustomStep.
    """

    def execute(self, ctx: ExecutorContext) -> CustomStepResult:
        """Execute custom step and return result."""
        start_time = time.time()
        step_def = ctx.step_def
        class_path = step_def.class_path

        if not class_path:
            return CustomStepResult(
                success=False,
                error="No class_path specified for custom step",
                duration_seconds=time.time() - start_time,
            )

        # Load the class
        try:
            step_class = self._load_class(class_path)
        except Exception as e:
            return CustomStepResult(
                success=False,
                class_name=class_path,
                error=f"Failed to load class: {e}",
                duration_seconds=time.time() - start_time,
            )

        # Instantiate with config
        try:
            step_instance = step_class(step_def.step_config)
        except Exception as e:
            return CustomStepResult(
                success=False,
                class_name=class_path,
                error=f"Failed to instantiate class: {e}",
                duration_seconds=time.time() - start_time,
            )

        # Execute
        try:
            result = step_instance.execute(ctx.step_ctx)
            duration = time.time() - start_time

            # If result is already a CustomStepResult, use it
            if isinstance(result, CustomStepResult):
                result.class_name = class_path
                result.duration_seconds = duration
                return result

            # Otherwise wrap it
            return CustomStepResult(
                success=result.success,
                class_name=class_path,
                data=result.to_dict() if hasattr(result, "to_dict") else {},
                duration_seconds=duration,
                error=result.error,
            )

        except Exception as e:
            return CustomStepResult(
                success=False,
                class_name=class_path,
                error=f"Execution failed: {e}",
                duration_seconds=time.time() - start_time,
            )

    def _load_class(self, class_path: str) -> type[CustomStep]:
        """Load a class from a module path.

        Args:
            class_path: Fully qualified class name (e.g., "mymodule.MyClass")

        Returns:
            The class object

        Raises:
            ImportError: If module cannot be imported
            AttributeError: If class not found in module
        """
        module_path, class_name = class_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)

        if not issubclass(cls, CustomStep):
            raise TypeError(f"{class_path} must be a subclass of CustomStep")

        return cls


def get_executor(step_type: str) -> StepExecutor:
    """Get the appropriate executor for a step type.

    Args:
        step_type: One of "shell", "llm_eval", "quality_check", "python"

    Returns:
        StepExecutor instance

    Raises:
        ValueError: If step type is unknown
    """
    executors: dict[str, type[StepExecutor]] = {
        "shell": ShellStepExecutor,
        "llm_eval": LLMEvalStepExecutor,
        "quality_check": QualityCheckStepExecutor,
        "python": CustomStepExecutor,
    }

    executor_class = executors.get(step_type)
    if executor_class is None:
        raise ValueError(
            f"Unknown step type: {step_type}. "
            f"Valid types: {', '.join(executors.keys())}"
        )

    return executor_class()
