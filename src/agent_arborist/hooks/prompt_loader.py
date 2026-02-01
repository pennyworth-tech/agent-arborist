"""Prompt loading and variable substitution for hooks."""

import re
from pathlib import Path
from typing import Any

from agent_arborist.hooks.base import StepContext


class PromptLoadError(Exception):
    """Raised when a prompt cannot be loaded."""

    pass


class PromptLoader:
    """Loads and processes prompts from files or inline text.

    Supports loading prompts from:
    - External files in a prompts directory
    - Inline text in configuration
    - Multiline arrays (joined with newlines)
    """

    def __init__(self, prompts_dir: Path):
        """Initialize the prompt loader.

        Args:
            prompts_dir: Directory containing prompt files.
        """
        self.prompts_dir = prompts_dir

    def load(self, step_config: dict[str, Any]) -> str:
        """Load prompt from configuration.

        Checks for prompt sources in order:
        1. prompt_file - Load from external file
        2. prompt - Use inline text (string or list of strings)

        Args:
            step_config: Step configuration dictionary

        Returns:
            The loaded prompt text

        Raises:
            PromptLoadError: If no prompt source is found or file doesn't exist
        """
        if step_config.get("prompt_file"):
            return self._load_file(step_config["prompt_file"])

        if "prompt" in step_config:
            prompt = step_config["prompt"]
            if isinstance(prompt, list):
                return "\n".join(str(line) for line in prompt)
            return str(prompt)

        raise PromptLoadError(
            "Step configuration requires 'prompt' or 'prompt_file'. "
            "Provide either inline text or a file reference."
        )

    def _load_file(self, filename: str) -> str:
        """Load prompt from file.

        Args:
            filename: Filename relative to prompts_dir

        Returns:
            File contents as string

        Raises:
            PromptLoadError: If file doesn't exist or can't be read
        """
        path = self.prompts_dir / filename

        if not path.exists():
            raise PromptLoadError(
                f"Prompt file not found: {path}\n"
                f"Create the file or use inline 'prompt' instead of 'prompt_file'."
            )

        try:
            return path.read_text()
        except OSError as e:
            raise PromptLoadError(f"Error reading prompt file {path}: {e}")

    def exists(self, filename: str) -> bool:
        """Check if a prompt file exists.

        Args:
            filename: Filename relative to prompts_dir

        Returns:
            True if the file exists
        """
        return (self.prompts_dir / filename).exists()


# Variable pattern: {{variable_name}}
VARIABLE_PATTERN = re.compile(r"\{\{(\w+)\}\}")


def substitute_variables(text: str, ctx: StepContext) -> str:
    """Substitute {{variable}} placeholders with context values.

    Available variables:
    - {{task_id}}: Current task ID
    - {{spec_id}}: Spec identifier
    - {{worktree_path}}: Absolute path to task worktree
    - {{branch_name}}: Git branch for task
    - {{parent_branch}}: Parent branch name
    - {{arborist_home}}: Path to .arborist directory
    - {{timestamp}}: ISO timestamp

    Args:
        text: Text containing {{variable}} placeholders
        ctx: Step context with variable values

    Returns:
        Text with all variables substituted

    Example:
        >>> ctx = StepContext(task_id="T001", spec_id="my-spec", ...)
        >>> substitute_variables("Task {{task_id}} in {{spec_id}}", ctx)
        "Task T001 in my-spec"
    """
    variables = ctx.to_variables()

    def replace_var(match: re.Match) -> str:
        var_name = match.group(1)
        if var_name in variables:
            return variables[var_name]
        # Leave unknown variables unchanged
        return match.group(0)

    return VARIABLE_PATTERN.sub(replace_var, text)


def substitute_variables_dict(
    text: str,
    variables: dict[str, str],
) -> str:
    """Substitute {{variable}} placeholders with dictionary values.

    This is a lower-level function for cases where you have a
    pre-built variables dictionary instead of a StepContext.

    Args:
        text: Text containing {{variable}} placeholders
        variables: Dictionary of variable name -> value

    Returns:
        Text with all variables substituted
    """

    def replace_var(match: re.Match) -> str:
        var_name = match.group(1)
        if var_name in variables:
            return variables[var_name]
        return match.group(0)

    return VARIABLE_PATTERN.sub(replace_var, text)


def get_available_variables() -> list[str]:
    """Get list of available variable names.

    Returns:
        List of variable names that can be used in templates.
    """
    return [
        "task_id",
        "spec_id",
        "worktree_path",
        "branch_name",
        "parent_branch",
        "arborist_home",
        "timestamp",
    ]


def validate_prompt_variables(text: str) -> list[str]:
    """Find any unknown variables in prompt text.

    Args:
        text: Prompt text to validate

    Returns:
        List of unknown variable names (empty if all valid)
    """
    available = set(get_available_variables())
    found = set(VARIABLE_PATTERN.findall(text))
    unknown = found - available
    return sorted(unknown)
