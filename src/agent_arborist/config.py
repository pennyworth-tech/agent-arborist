"""Configuration system for Agent Arborist.

Provides hierarchical configuration with precedence:
1. CLI flags (highest)
2. Environment variables
3. Step-specific env vars
4. Project config (.arborist/config.json)
5. Global config (~/.arborist_config.json)
6. Hardcoded defaults (lowest)
"""

from __future__ import annotations

import copy
import json
import logging
import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Valid values for enums
VALID_RUNNERS = ("claude", "opencode", "gemini")
VALID_OUTPUT_FORMATS = ("json", "text")
VALID_CONTAINER_MODES = ("auto", "enabled", "disabled")
VALID_STEPS = ("run", "post-merge")

# Hardcoded defaults
DEFAULT_RUNNER = "claude"
DEFAULT_MODEL = "sonnet"

# Environment variable names
ENV_RUNNER = "ARBORIST_RUNNER"
ENV_MODEL = "ARBORIST_MODEL"
ENV_OUTPUT_FORMAT = "ARBORIST_OUTPUT_FORMAT"
ENV_CONTAINER_MODE = "ARBORIST_CONTAINER_MODE"
ENV_QUIET = "ARBORIST_QUIET"
ENV_TIMEOUT_TASK_RUN = "ARBORIST_TIMEOUT_TASK_RUN"
ENV_TIMEOUT_POST_MERGE = "ARBORIST_TIMEOUT_POST_MERGE"
ENV_TEST_COMMAND = "ARBORIST_TEST_COMMAND"
ENV_TEST_TIMEOUT = "ARBORIST_TEST_TIMEOUT"

# Deprecated env vars (backward compatibility)
ENV_DEFAULT_RUNNER_DEPRECATED = "ARBORIST_DEFAULT_RUNNER"
ENV_DEFAULT_MODEL_DEPRECATED = "ARBORIST_DEFAULT_MODEL"

# Step-specific env var pattern
ENV_STEP_RUNNER_TEMPLATE = "ARBORIST_STEP_{step}_RUNNER"
ENV_STEP_MODEL_TEMPLATE = "ARBORIST_STEP_{step}_MODEL"


class ConfigValidationError(Exception):
    """Raised when configuration validation fails."""

    pass


class ConfigLoadError(Exception):
    """Raised when configuration file cannot be loaded."""

    pass


@dataclass
class DefaultsConfig:
    """Default configuration values."""

    runner: str | None = None
    model: str | None = None
    output_format: str = "json"
    container_mode: str = "auto"
    quiet: bool = False

    def validate(self) -> None:
        """Validate configuration values."""
        if self.runner is not None and self.runner not in VALID_RUNNERS:
            raise ConfigValidationError(
                f"Invalid runner '{self.runner}'. "
                f"Valid values: {', '.join(VALID_RUNNERS)}"
            )
        if self.output_format not in VALID_OUTPUT_FORMATS:
            raise ConfigValidationError(
                f"Invalid output_format '{self.output_format}'. "
                f"Valid values: {', '.join(VALID_OUTPUT_FORMATS)}"
            )
        if self.container_mode not in VALID_CONTAINER_MODES:
            raise ConfigValidationError(
                f"Invalid container_mode '{self.container_mode}'. "
                f"Valid values: {', '.join(VALID_CONTAINER_MODES)}"
            )

    def to_dict(self, exclude_none: bool = False) -> dict[str, Any]:
        """Convert to dictionary."""
        result = {
            "runner": self.runner,
            "model": self.model,
            "output_format": self.output_format,
            "container_mode": self.container_mode,
            "quiet": self.quiet,
        }
        if exclude_none:
            return {k: v for k, v in result.items() if v is not None}
        return result

    @classmethod
    def from_dict(
        cls, data: dict[str, Any], strict: bool = False
    ) -> "DefaultsConfig":
        """Create from dictionary."""
        if strict:
            known_fields = {f.name for f in fields(cls)}
            unknown = set(data.keys()) - known_fields
            if unknown:
                raise ConfigValidationError(
                    f"Unknown fields in defaults config: {', '.join(unknown)}"
                )

        return cls(
            runner=data.get("runner"),
            model=data.get("model"),
            output_format=data.get("output_format", "json"),
            container_mode=data.get("container_mode", "auto"),
            quiet=data.get("quiet", False),
        )


@dataclass
class TimeoutConfig:
    """Timeout configuration values."""

    task_run: int = 1800
    task_post_merge: int = 300
    test_command: int | None = None

    def validate(self) -> None:
        """Validate timeout values."""
        if self.task_run <= 0:
            raise ConfigValidationError(
                f"task_run timeout must be positive, got {self.task_run}"
            )
        if self.task_post_merge <= 0:
            raise ConfigValidationError(
                f"task_post_merge timeout must be positive, got {self.task_post_merge}"
            )
        if self.test_command is not None and self.test_command <= 0:
            raise ConfigValidationError(
                f"test_command timeout must be positive, got {self.test_command}"
            )

    def to_dict(self, exclude_none: bool = False) -> dict[str, Any]:
        """Convert to dictionary."""
        result = {
            "task_run": self.task_run,
            "task_post_merge": self.task_post_merge,
            "test_command": self.test_command,
        }
        if exclude_none:
            return {k: v for k, v in result.items() if v is not None}
        return result

    @classmethod
    def from_dict(
        cls, data: dict[str, Any], strict: bool = False
    ) -> "TimeoutConfig":
        """Create from dictionary."""
        if strict:
            known_fields = {f.name for f in fields(cls)}
            unknown = set(data.keys()) - known_fields
            if unknown:
                raise ConfigValidationError(
                    f"Unknown fields in timeouts config: {', '.join(unknown)}"
                )

        return cls(
            task_run=data.get("task_run", 1800),
            task_post_merge=data.get("task_post_merge", 300),
            test_command=data.get("test_command"),
        )


@dataclass
class StepConfig:
    """Step-specific runner/model configuration."""

    runner: str | None = None
    model: str | None = None

    def validate(self) -> None:
        """Validate step configuration."""
        if self.runner is not None and self.runner not in VALID_RUNNERS:
            raise ConfigValidationError(
                f"Invalid step runner '{self.runner}'. "
                f"Valid values: {', '.join(VALID_RUNNERS)}"
            )

    def to_dict(self, exclude_none: bool = False) -> dict[str, Any]:
        """Convert to dictionary."""
        result = {"runner": self.runner, "model": self.model}
        if exclude_none:
            return {k: v for k, v in result.items() if v is not None}
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any], strict: bool = False) -> "StepConfig":
        """Create from dictionary."""
        if strict:
            known_fields = {f.name for f in fields(cls)}
            unknown = set(data.keys()) - known_fields
            if unknown:
                raise ConfigValidationError(
                    f"Unknown fields in step config: {', '.join(unknown)}"
                )

        return cls(
            runner=data.get("runner"),
            model=data.get("model"),
        )


@dataclass
class RunnerConfig:
    """Runner-specific configuration."""

    default_model: str | None = None
    models: dict[str, str] = field(default_factory=dict)
    timeout: int | None = None

    def to_dict(self, exclude_none: bool = False) -> dict[str, Any]:
        """Convert to dictionary."""
        result = {
            "default_model": self.default_model,
            "models": self.models,
            "timeout": self.timeout,
        }
        if exclude_none:
            return {k: v for k, v in result.items() if v is not None}
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any], strict: bool = False) -> "RunnerConfig":
        """Create from dictionary."""
        if strict:
            known_fields = {f.name for f in fields(cls)}
            unknown = set(data.keys()) - known_fields
            if unknown:
                raise ConfigValidationError(
                    f"Unknown fields in runner config: {', '.join(unknown)}"
                )

        return cls(
            default_model=data.get("default_model"),
            models=data.get("models", {}),
            timeout=data.get("timeout"),
        )


@dataclass
class TestingConfig:
    """Testing/test command configuration."""

    command: str | None = None
    timeout: int | None = None

    def to_dict(self, exclude_none: bool = False) -> dict[str, Any]:
        """Convert to dictionary."""
        result = {"command": self.command, "timeout": self.timeout}
        if exclude_none:
            return {k: v for k, v in result.items() if v is not None}
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any], strict: bool = False) -> "TestingConfig":
        """Create from dictionary."""
        if strict:
            known_fields = {f.name for f in fields(cls)}
            unknown = set(data.keys()) - known_fields
            if unknown:
                raise ConfigValidationError(
                    f"Unknown fields in test config: {', '.join(unknown)}"
                )

        return cls(
            command=data.get("command"),
            timeout=data.get("timeout"),
        )


# Alias for backward compatibility
TestConfig = TestingConfig


@dataclass
class PathsConfig:
    """Path configuration."""

    worktrees: str = "worktrees"
    dags: str = "dagu"

    def to_dict(self, exclude_none: bool = False) -> dict[str, Any]:
        """Convert to dictionary."""
        return {"worktrees": self.worktrees, "dags": self.dags}

    @classmethod
    def from_dict(cls, data: dict[str, Any], strict: bool = False) -> "PathsConfig":
        """Create from dictionary."""
        if strict:
            known_fields = {f.name for f in fields(cls)}
            unknown = set(data.keys()) - known_fields
            if unknown:
                raise ConfigValidationError(
                    f"Unknown fields in paths config: {', '.join(unknown)}"
                )

        return cls(
            worktrees=data.get("worktrees", "worktrees"),
            dags=data.get("dags", "dagu"),
        )


@dataclass
class ArboristConfig:
    """Main configuration container."""

    version: str = "1"
    defaults: DefaultsConfig = field(default_factory=DefaultsConfig)
    timeouts: TimeoutConfig = field(default_factory=TimeoutConfig)
    steps: dict[str, StepConfig] = field(
        default_factory=lambda: {
            "run": StepConfig(),
            "post-merge": StepConfig(),
        }
    )
    test: TestingConfig = field(default_factory=TestingConfig)
    paths: PathsConfig = field(default_factory=PathsConfig)
    runners: dict[str, RunnerConfig] = field(default_factory=dict)

    def validate(self) -> None:
        """Validate entire configuration."""
        self.defaults.validate()
        self.timeouts.validate()

        # Validate step names
        for step_name in self.steps:
            if step_name not in VALID_STEPS:
                raise ConfigValidationError(
                    f"Unknown step name '{step_name}'. "
                    f"Valid steps: {', '.join(VALID_STEPS)}"
                )
            self.steps[step_name].validate()

    def to_dict(self, exclude_none: bool = False) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "version": self.version,
            "defaults": self.defaults.to_dict(exclude_none),
            "timeouts": self.timeouts.to_dict(exclude_none),
            "steps": {k: v.to_dict(exclude_none) for k, v in self.steps.items()},
            "test": self.test.to_dict(exclude_none),
            "paths": self.paths.to_dict(exclude_none),
            "runners": {k: v.to_dict(exclude_none) for k, v in self.runners.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], strict: bool = False) -> "ArboristConfig":
        """Create from dictionary."""
        if strict:
            known_fields = {
                "version",
                "defaults",
                "timeouts",
                "steps",
                "test",
                "paths",
                "runners",
            }
            unknown = set(data.keys()) - known_fields
            if unknown:
                raise ConfigValidationError(
                    f"Unknown fields in config: {', '.join(unknown)}"
                )

        # Parse steps
        steps_data = data.get("steps", {})
        steps = {
            "run": StepConfig.from_dict(steps_data.get("run", {}), strict),
            "post-merge": StepConfig.from_dict(steps_data.get("post-merge", {}), strict),
        }
        # Add any additional steps from data
        for step_name, step_data in steps_data.items():
            if step_name not in steps:
                steps[step_name] = StepConfig.from_dict(step_data, strict)

        # Parse runners
        runners_data = data.get("runners", {})
        runners = {
            name: RunnerConfig.from_dict(runner_data, strict)
            for name, runner_data in runners_data.items()
        }

        return cls(
            version=data.get("version", "1"),
            defaults=DefaultsConfig.from_dict(data.get("defaults", {}), strict),
            timeouts=TimeoutConfig.from_dict(data.get("timeouts", {}), strict),
            steps=steps,
            test=TestingConfig.from_dict(data.get("test", {}), strict),
            paths=PathsConfig.from_dict(data.get("paths", {}), strict),
            runners=runners,
        )


def get_global_config_path() -> Path:
    """Get path to global config file."""
    return Path.home() / ".arborist_config.json"


def get_project_config_path(arborist_home: Path) -> Path:
    """Get path to project config file."""
    return arborist_home / "config.json"


def load_config_file(path: Path, strict: bool = False) -> ArboristConfig:
    """Load configuration from a JSON file.

    Args:
        path: Path to the config file
        strict: If True, fail on unknown fields

    Returns:
        ArboristConfig instance

    Raises:
        ConfigLoadError: If file cannot be read or parsed
        ConfigValidationError: If strict=True and unknown fields found
    """
    if not path.exists():
        return ArboristConfig()

    try:
        content = path.read_text()
    except PermissionError as e:
        raise ConfigLoadError(f"Permission denied reading {path}: {e}")
    except OSError as e:
        raise ConfigLoadError(f"Error reading {path}: {e}")

    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise ConfigLoadError(f"Invalid JSON in {path}: {e}")

    return ArboristConfig.from_dict(data, strict=strict)


def merge_configs(*configs: ArboristConfig) -> ArboristConfig:
    """Merge multiple configs with later configs taking precedence.

    None values in later configs do NOT override earlier values.
    This allows partial configs to be layered properly.

    Args:
        *configs: Configs to merge (first is base, last has highest priority)

    Returns:
        Merged ArboristConfig
    """
    if not configs:
        return ArboristConfig()

    result = copy.deepcopy(configs[0])

    for config in configs[1:]:
        # Merge defaults (only non-None values)
        if config.defaults.runner is not None:
            result.defaults.runner = config.defaults.runner
        if config.defaults.model is not None:
            result.defaults.model = config.defaults.model
        if config.defaults.output_format != "json":  # non-default
            result.defaults.output_format = config.defaults.output_format
        if config.defaults.container_mode != "auto":  # non-default
            result.defaults.container_mode = config.defaults.container_mode
        if config.defaults.quiet:  # non-default
            result.defaults.quiet = config.defaults.quiet

        # Merge timeouts (only non-default values)
        if config.timeouts.task_run != 1800:
            result.timeouts.task_run = config.timeouts.task_run
        if config.timeouts.task_post_merge != 300:
            result.timeouts.task_post_merge = config.timeouts.task_post_merge
        if config.timeouts.test_command is not None:
            result.timeouts.test_command = config.timeouts.test_command

        # Merge steps (only non-None values)
        for step_name, step_config in config.steps.items():
            if step_name not in result.steps:
                result.steps[step_name] = StepConfig()
            if step_config.runner is not None:
                result.steps[step_name].runner = step_config.runner
            if step_config.model is not None:
                result.steps[step_name].model = step_config.model

        # Merge test config
        if config.test.command is not None:
            result.test.command = config.test.command
        if config.test.timeout is not None:
            result.test.timeout = config.test.timeout

        # Merge paths (only non-default values)
        if config.paths.worktrees != "worktrees":
            result.paths.worktrees = config.paths.worktrees
        if config.paths.dags != "dagu":
            result.paths.dags = config.paths.dags

        # Merge runners
        for runner_name, runner_config in config.runners.items():
            if runner_name not in result.runners:
                result.runners[runner_name] = RunnerConfig()
            if runner_config.default_model is not None:
                result.runners[runner_name].default_model = runner_config.default_model
            if runner_config.models:
                result.runners[runner_name].models.update(runner_config.models)
            if runner_config.timeout is not None:
                result.runners[runner_name].timeout = runner_config.timeout

    return result


def apply_env_overrides(config: ArboristConfig) -> ArboristConfig:
    """Apply environment variable overrides to config.

    Args:
        config: Base configuration

    Returns:
        New config with env var overrides applied

    Raises:
        ConfigValidationError: If env var value is invalid
    """
    result = copy.deepcopy(config)

    # Check deprecated env vars first (with warnings)
    deprecated_runner = os.environ.get(ENV_DEFAULT_RUNNER_DEPRECATED)
    if deprecated_runner and not os.environ.get(ENV_RUNNER):
        logger.warning(
            f"{ENV_DEFAULT_RUNNER_DEPRECATED} is deprecated. "
            f"Use {ENV_RUNNER} instead."
        )
        result.defaults.runner = deprecated_runner

    deprecated_model = os.environ.get(ENV_DEFAULT_MODEL_DEPRECATED)
    if deprecated_model and not os.environ.get(ENV_MODEL):
        logger.warning(
            f"{ENV_DEFAULT_MODEL_DEPRECATED} is deprecated. "
            f"Use {ENV_MODEL} instead."
        )
        result.defaults.model = deprecated_model

    # Apply new env vars (override deprecated)
    if runner := os.environ.get(ENV_RUNNER):
        result.defaults.runner = runner

    if model := os.environ.get(ENV_MODEL):
        result.defaults.model = model

    if output_format := os.environ.get(ENV_OUTPUT_FORMAT):
        result.defaults.output_format = output_format

    if container_mode := os.environ.get(ENV_CONTAINER_MODE):
        result.defaults.container_mode = container_mode

    if quiet := os.environ.get(ENV_QUIET):
        result.defaults.quiet = quiet.lower() in ("true", "1", "yes")

    # Timeout overrides
    if task_run_str := os.environ.get(ENV_TIMEOUT_TASK_RUN):
        try:
            result.timeouts.task_run = int(task_run_str)
        except ValueError:
            raise ConfigValidationError(
                f"{ENV_TIMEOUT_TASK_RUN} must be an integer, got '{task_run_str}'"
            )

    if post_merge_str := os.environ.get(ENV_TIMEOUT_POST_MERGE):
        try:
            result.timeouts.task_post_merge = int(post_merge_str)
        except ValueError:
            raise ConfigValidationError(
                f"{ENV_TIMEOUT_POST_MERGE} must be an integer, got '{post_merge_str}'"
            )

    # Test config overrides
    if test_command := os.environ.get(ENV_TEST_COMMAND):
        result.test.command = test_command

    if test_timeout_str := os.environ.get(ENV_TEST_TIMEOUT):
        try:
            result.test.timeout = int(test_timeout_str)
        except ValueError:
            raise ConfigValidationError(
                f"{ENV_TEST_TIMEOUT} must be an integer, got '{test_timeout_str}'"
            )

    # Step-specific env vars
    for step_name in VALID_STEPS:
        step_upper = step_name.upper().replace("-", "_")
        runner_var = ENV_STEP_RUNNER_TEMPLATE.format(step=step_upper)
        model_var = ENV_STEP_MODEL_TEMPLATE.format(step=step_upper)

        if step_runner := os.environ.get(runner_var):
            if step_name not in result.steps:
                result.steps[step_name] = StepConfig()
            result.steps[step_name].runner = step_runner

        if step_model := os.environ.get(model_var):
            if step_name not in result.steps:
                result.steps[step_name] = StepConfig()
            result.steps[step_name].model = step_model

    return result


def get_config(arborist_home: Path | None = None) -> ArboristConfig:
    """Load and merge configuration from all sources.

    Loads in order (later sources override earlier):
    1. Hardcoded defaults
    2. Global config (~/.arborist_config.json)
    3. Project config (.arborist/config.json)
    4. Environment variables

    Args:
        arborist_home: Path to .arborist directory (for project config)

    Returns:
        Merged configuration with all overrides applied
    """
    # Start with defaults
    base_config = ArboristConfig()

    # Load global config
    global_path = get_global_config_path()
    global_config = load_config_file(global_path)

    # Load project config
    project_config = ArboristConfig()
    if arborist_home is not None:
        project_path = get_project_config_path(arborist_home)
        project_config = load_config_file(project_path)

    # Merge configs
    merged = merge_configs(base_config, global_config, project_config)

    # Apply env var overrides
    return apply_env_overrides(merged)


def get_step_runner_model(
    config: ArboristConfig,
    step: str,
    cli_runner: str | None = None,
    cli_model: str | None = None,
) -> tuple[str, str]:
    """Resolve runner and model for a specific step.

    Precedence (highest to lowest):
    1. CLI flags
    2. Step-specific config
    3. Defaults config
    4. Hardcoded defaults

    Runner and model resolve independently.

    Args:
        config: Merged configuration
        step: Step name (e.g., "run", "post-merge")
        cli_runner: Optional runner from CLI flag
        cli_model: Optional model from CLI flag

    Returns:
        Tuple of (runner, model)
    """
    # Get step config (or empty)
    step_config = config.steps.get(step, StepConfig())

    # Resolve runner: CLI > step config > defaults > hardcoded
    if cli_runner is not None:
        runner = cli_runner
    elif step_config.runner is not None:
        runner = step_config.runner
    elif config.defaults.runner is not None:
        runner = config.defaults.runner
    else:
        runner = DEFAULT_RUNNER

    # Resolve model: CLI > step config > defaults > hardcoded
    if cli_model is not None:
        model = cli_model
    elif step_config.model is not None:
        model = step_config.model
    elif config.defaults.model is not None:
        model = config.defaults.model
    else:
        model = DEFAULT_MODEL

    return runner, model


def resolve_model_alias(
    config: ArboristConfig, runner: str, model: str
) -> str:
    """Resolve model alias to full model name.

    Looks up model in runner's models dict. If not found,
    returns the model name as-is.

    Args:
        config: Configuration with runners section
        runner: Runner name (e.g., "claude", "gemini")
        model: Model name or alias

    Returns:
        Full model name
    """
    runner_config = config.runners.get(runner)
    if runner_config is None:
        return model

    return runner_config.models.get(model, model)


def generate_config_template() -> dict[str, Any]:
    """Generate a config template dictionary.

    Returns:
        Dictionary suitable for JSON serialization
    """
    return {
        "version": "1",
        "_comment_version": "Config file format version",
        "defaults": {
            "runner": None,
            "_comment_runner": f"AI runner to use. Valid: {', '.join(VALID_RUNNERS)}",
            "model": None,
            "_comment_model": "Model to use with the runner (e.g., 'sonnet', 'opus')",
            "output_format": "json",
            "_comment_output_format": f"Output format. Valid: {', '.join(VALID_OUTPUT_FORMATS)}",
            "container_mode": "auto",
            "_comment_container_mode": f"Container mode. Valid: {', '.join(VALID_CONTAINER_MODES)}",
            "quiet": False,
            "_comment_quiet": "Suppress non-essential output",
        },
        "timeouts": {
            "task_run": 1800,
            "_comment_task_run": "Timeout for task run in seconds (default: 30 min)",
            "task_post_merge": 300,
            "_comment_task_post_merge": "Timeout for post-merge in seconds (default: 5 min)",
            "test_command": None,
            "_comment_test_command": "Timeout for test command in seconds",
        },
        "steps": {
            "run": {
                "runner": None,
                "model": None,
                "_comment": "Override runner/model for 'run' step",
            },
            "post-merge": {
                "runner": None,
                "model": None,
                "_comment": "Override runner/model for 'post-merge' step",
            },
        },
        "test": {
            "command": None,
            "_comment_command": "Custom test command (e.g., 'pytest -v')",
            "timeout": None,
            "_comment_timeout": "Test timeout in seconds",
        },
        "paths": {
            "worktrees": "worktrees",
            "_comment_worktrees": "Directory for git worktrees (relative to project root)",
            "dags": "dagu",
            "_comment_dags": "Directory for DAG files (relative to .arborist)",
        },
        "runners": {
            "claude": {
                "default_model": "sonnet",
                "models": {
                    "sonnet": "claude-3-5-sonnet-20241022",
                    "opus": "claude-3-opus-20240229",
                    "haiku": "claude-3-5-haiku-20241022",
                },
                "_comment": "Claude runner configuration with model aliases",
            },
            "opencode": {
                "default_model": "cerebras/llama-4-scout-17b",
                "models": {},
                "_comment": "OpenCode runner configuration",
            },
            "gemini": {
                "default_model": "gemini-2.5-flash",
                "models": {
                    "flash": "gemini-2.5-flash",
                    "pro": "gemini-2.5-pro",
                },
                "_comment": "Gemini runner configuration",
            },
        },
    }


def generate_config_template_string() -> str:
    """Generate a config template as a formatted JSON string.

    The string includes comments explaining each field.

    Returns:
        Formatted JSON string
    """
    template = generate_config_template()
    return json.dumps(template, indent=2)
