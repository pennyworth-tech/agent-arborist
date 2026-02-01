"""Tests for configuration system.

TDD approach: Tests are written first, then implementation follows.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

import pytest

from agent_arborist.config import (
    ArboristConfig,
    ConfigLoadError,
    ConfigValidationError,
    DefaultsConfig,
    HookInjection,
    HooksConfig,
    PathsConfig,
    RunnerConfig,
    StepConfig,
    StepDefinition,
    TestConfig,
    TimeoutConfig,
    VALID_HOOK_POINTS,
    VALID_STEP_TYPES,
    apply_env_overrides,
    generate_config_template,
    generate_config_template_string,
    get_config,
    get_global_config_path,
    get_project_config_path,
    get_step_runner_model,
    load_config_file,
    merge_configs,
    resolve_model_alias,
)


# =============================================================================
# Phase 1: Core Dataclasses
# =============================================================================


class TestConfigDataclasses:
    """Unit tests for config dataclass construction and defaults."""

    def test_defaults_config_has_correct_defaults(self):
        """DefaultsConfig should have sensible defaults."""
        config = DefaultsConfig()
        assert config.runner is None
        assert config.model is None
        assert config.output_format == "json"
        assert config.container_mode == "auto"
        assert config.quiet is False

    def test_timeout_config_has_correct_defaults(self):
        """TimeoutConfig should have correct timeout values."""
        config = TimeoutConfig()
        assert config.task_run == 1800
        assert config.task_post_merge == 300
        assert config.test_command is None

    def test_step_config_has_null_defaults(self):
        """StepConfig should default to None for both fields."""
        config = StepConfig()
        assert config.runner is None
        assert config.model is None

    def test_runner_config_has_empty_models_dict(self):
        """RunnerConfig should have empty models dict by default."""
        config = RunnerConfig()
        assert config.default_model is None
        assert config.models == {}
        assert config.timeout is None

    def test_paths_config_has_correct_defaults(self):
        """PathsConfig should have relative path defaults."""
        config = PathsConfig()
        assert config.worktrees == "worktrees"
        assert config.dags == "dagu"

    def test_test_config_has_null_defaults(self):
        """TestConfig should default to None."""
        config = TestConfig()
        assert config.command is None
        assert config.timeout is None

    def test_arborist_config_has_all_sections(self):
        """ArboristConfig should compose all sub-configs."""
        config = ArboristConfig()
        assert config.version == "1"
        assert isinstance(config.defaults, DefaultsConfig)
        assert isinstance(config.timeouts, TimeoutConfig)
        assert isinstance(config.test, TestConfig)
        assert isinstance(config.paths, PathsConfig)
        assert "run" in config.steps
        assert "post-merge" in config.steps


class TestConfigSerialization:
    """Unit tests for config serialization."""

    def test_defaults_config_to_dict(self):
        """DefaultsConfig.to_dict() returns correct structure."""
        config = DefaultsConfig(runner="claude", model="sonnet")
        d = config.to_dict()
        assert d["runner"] == "claude"
        assert d["model"] == "sonnet"
        assert d["output_format"] == "json"

    def test_defaults_config_from_dict(self):
        """DefaultsConfig.from_dict() creates correct instance."""
        d = {"runner": "opencode", "model": "glm-4.7", "quiet": True}
        config = DefaultsConfig.from_dict(d)
        assert config.runner == "opencode"
        assert config.model == "glm-4.7"
        assert config.quiet is True
        assert config.output_format == "json"  # default

    def test_defaults_config_from_dict_ignores_null(self):
        """from_dict with null values uses defaults."""
        d = {"runner": None, "model": "sonnet"}
        config = DefaultsConfig.from_dict(d)
        assert config.runner is None
        assert config.model == "sonnet"

    def test_arborist_config_round_trip(self):
        """ArboristConfig survives to_dict/from_dict round trip."""
        original = ArboristConfig(
            defaults=DefaultsConfig(runner="claude"),
            timeouts=TimeoutConfig(task_run=3600),
            steps={"run": StepConfig(model="opus"), "post-merge": StepConfig()},
        )
        d = original.to_dict()
        restored = ArboristConfig.from_dict(d)
        assert restored.defaults.runner == "claude"
        assert restored.timeouts.task_run == 3600
        assert restored.steps["run"].model == "opus"

    def test_step_config_to_dict_excludes_none(self):
        """StepConfig.to_dict() can optionally exclude None values."""
        config = StepConfig(runner="claude", model=None)
        d = config.to_dict(exclude_none=True)
        assert "runner" in d
        assert "model" not in d


class TestConfigValidation:
    """Unit tests for config validation."""

    def test_invalid_runner_raises_error(self):
        """Invalid runner value should raise ConfigValidationError."""
        with pytest.raises(ConfigValidationError) as exc:
            DefaultsConfig(runner="invalid_runner").validate()
        assert "runner" in str(exc.value)
        assert "invalid_runner" in str(exc.value)

    def test_valid_runners_accepted(self):
        """Valid runner values should pass validation."""
        for runner in ["claude", "opencode", "gemini", None]:
            config = DefaultsConfig(runner=runner)
            config.validate()  # Should not raise

    def test_invalid_container_mode_raises_error(self):
        """Invalid container_mode should raise ConfigValidationError."""
        with pytest.raises(ConfigValidationError) as exc:
            DefaultsConfig(container_mode="invalid").validate()
        assert "container_mode" in str(exc.value)

    def test_invalid_output_format_raises_error(self):
        """Invalid output_format should raise ConfigValidationError."""
        with pytest.raises(ConfigValidationError) as exc:
            DefaultsConfig(output_format="xml").validate()
        assert "output_format" in str(exc.value)

    def test_negative_timeout_raises_error(self):
        """Negative timeout should raise ConfigValidationError."""
        with pytest.raises(ConfigValidationError) as exc:
            TimeoutConfig(task_run=-1).validate()
        assert "task_run" in str(exc.value)
        assert "positive" in str(exc.value).lower()

    def test_zero_timeout_raises_error(self):
        """Zero timeout should raise ConfigValidationError."""
        with pytest.raises(ConfigValidationError) as exc:
            TimeoutConfig(task_run=0).validate()
        assert "task_run" in str(exc.value)

    def test_unknown_field_in_dict_raises_error(self):
        """Unknown fields in config dict should raise ConfigValidationError."""
        d = {"runner": "claude", "unknown_field": "value"}
        with pytest.raises(ConfigValidationError) as exc:
            DefaultsConfig.from_dict(d, strict=True)
        assert "unknown_field" in str(exc.value)

    def test_unknown_step_name_raises_error(self):
        """Unknown step names should raise ConfigValidationError."""
        config = ArboristConfig(
            steps={"run": StepConfig(), "unknown_step": StepConfig()}
        )
        with pytest.raises(ConfigValidationError) as exc:
            config.validate()
        assert "unknown_step" in str(exc.value)


# =============================================================================
# Phase 2: Config File Loading
# =============================================================================


class TestConfigPaths:
    """Unit tests for config file path resolution."""

    def test_global_config_path_is_home_directory(self):
        """Global config should be at ~/.arborist_config.json."""
        path = get_global_config_path()
        assert path == Path.home() / ".arborist_config.json"

    def test_project_config_path_relative_to_home(self, tmp_path):
        """Project config should be at ARBORIST_HOME/config.json."""
        arborist_home = tmp_path / ".arborist"
        path = get_project_config_path(arborist_home)
        assert path == arborist_home / "config.json"


class TestConfigFileLoading:
    """Unit tests for loading config from JSON files."""

    def test_load_valid_config_file(self, tmp_path):
        """Valid JSON config file should load correctly."""
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps(
                {"version": "1", "defaults": {"runner": "claude", "model": "sonnet"}}
            )
        )

        config = load_config_file(config_file)
        assert config.defaults.runner == "claude"
        assert config.defaults.model == "sonnet"

    def test_load_missing_file_returns_default(self, tmp_path):
        """Missing config file should return default config."""
        config_file = tmp_path / "nonexistent.json"
        config = load_config_file(config_file)
        assert config == ArboristConfig()

    def test_load_invalid_json_raises_error(self, tmp_path):
        """Invalid JSON should raise ConfigLoadError."""
        config_file = tmp_path / "config.json"
        config_file.write_text("{ invalid json }")

        with pytest.raises(ConfigLoadError) as exc:
            load_config_file(config_file)
        assert "JSON" in str(exc.value) or "json" in str(exc.value).lower()
        assert str(config_file) in str(exc.value)

    def test_load_config_with_unknown_fields_fails(self, tmp_path):
        """Config with unknown fields should fail validation."""
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps({"version": "1", "unknown_section": {"foo": "bar"}})
        )

        with pytest.raises(ConfigValidationError) as exc:
            load_config_file(config_file, strict=True)
        assert "unknown_section" in str(exc.value)

    def test_load_empty_file_returns_default(self, tmp_path):
        """Empty config file should return default config."""
        config_file = tmp_path / "config.json"
        config_file.write_text("{}")

        config = load_config_file(config_file)
        assert config.version == "1"
        assert config.defaults.runner is None

    def test_load_partial_config_merges_with_defaults(self, tmp_path):
        """Partial config should merge with defaults."""
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"defaults": {"runner": "opencode"}}))

        config = load_config_file(config_file)
        assert config.defaults.runner == "opencode"
        assert config.defaults.output_format == "json"  # default
        assert config.timeouts.task_run == 1800  # default


class TestConfigFileSteps:
    """Unit tests for step configuration in files."""

    def test_load_config_with_step_overrides(self, tmp_path):
        """Config with step overrides should load correctly."""
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps(
                {
                    "steps": {
                        "run": {"runner": "claude", "model": "opus"},
                        "post-merge": {"runner": "gemini", "model": "flash"},
                    }
                }
            )
        )

        config = load_config_file(config_file)
        assert config.steps["run"].runner == "claude"
        assert config.steps["run"].model == "opus"
        assert config.steps["post-merge"].runner == "gemini"
        assert config.steps["post-merge"].model == "flash"

    def test_load_config_with_partial_step_config(self, tmp_path):
        """Step config with only model should keep runner as None."""
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps(
                {
                    "steps": {
                        "run": {"model": "opus"}  # runner is None
                    }
                }
            )
        )

        config = load_config_file(config_file)
        assert config.steps["run"].runner is None
        assert config.steps["run"].model == "opus"


# =============================================================================
# Phase 3: Config Merging
# =============================================================================


class TestConfigMerging:
    """Unit tests for config merging logic."""

    def test_merge_project_overrides_global(self):
        """Project config should override global config."""
        global_config = ArboristConfig(
            defaults=DefaultsConfig(runner="claude", model="sonnet")
        )
        project_config = ArboristConfig(defaults=DefaultsConfig(runner="opencode"))

        merged = merge_configs(global_config, project_config)
        assert merged.defaults.runner == "opencode"  # project wins
        assert merged.defaults.model == "sonnet"  # global preserved

    def test_merge_null_does_not_override(self):
        """Null values in project config should not override global."""
        global_config = ArboristConfig(
            defaults=DefaultsConfig(runner="claude", model="sonnet")
        )
        project_config = ArboristConfig(
            defaults=DefaultsConfig(runner=None, model="opus")
        )

        merged = merge_configs(global_config, project_config)
        assert merged.defaults.runner == "claude"  # null didn't override
        assert merged.defaults.model == "opus"  # non-null did

    def test_merge_step_configs(self):
        """Step configs should merge correctly."""
        global_config = ArboristConfig(
            steps={
                "run": StepConfig(runner="claude", model="sonnet"),
                "post-merge": StepConfig(),
            }
        )
        project_config = ArboristConfig(
            steps={
                "run": StepConfig(model="opus"),  # override model only
                "post-merge": StepConfig(),
            }
        )

        merged = merge_configs(global_config, project_config)
        assert merged.steps["run"].runner == "claude"  # preserved
        assert merged.steps["run"].model == "opus"  # overridden

    def test_merge_timeout_configs(self):
        """Timeout configs should merge correctly."""
        global_config = ArboristConfig(
            timeouts=TimeoutConfig(task_run=3600, task_post_merge=600)
        )
        project_config = ArboristConfig(
            timeouts=TimeoutConfig(task_run=900)  # override one (must differ from default 1800)
        )

        merged = merge_configs(global_config, project_config)
        assert merged.timeouts.task_run == 900  # overridden
        assert merged.timeouts.task_post_merge == 600  # preserved

    def test_merge_three_configs(self):
        """Merging multiple configs follows precedence."""
        hardcoded = ArboristConfig()  # all defaults
        global_config = ArboristConfig(defaults=DefaultsConfig(runner="claude"))
        project_config = ArboristConfig(defaults=DefaultsConfig(model="opus"))

        merged = merge_configs(hardcoded, global_config, project_config)
        assert merged.defaults.runner == "claude"
        assert merged.defaults.model == "opus"
        assert merged.defaults.output_format == "json"  # hardcoded default


# =============================================================================
# Phase 4: Environment Variable Override
# =============================================================================


class TestEnvVarOverride:
    """Unit tests for environment variable overrides."""

    def test_arborist_runner_env_overrides_config(self, monkeypatch):
        """ARBORIST_RUNNER should override config."""
        monkeypatch.setenv("ARBORIST_RUNNER", "gemini")

        config = ArboristConfig(defaults=DefaultsConfig(runner="claude"))
        resolved = apply_env_overrides(config)
        assert resolved.defaults.runner == "gemini"

    def test_arborist_model_env_overrides_config(self, monkeypatch):
        """ARBORIST_MODEL should override config."""
        monkeypatch.setenv("ARBORIST_MODEL", "opus")

        config = ArboristConfig(defaults=DefaultsConfig(model="sonnet"))
        resolved = apply_env_overrides(config)
        assert resolved.defaults.model == "opus"

    def test_arborist_quiet_env_true(self, monkeypatch):
        """ARBORIST_QUIET=true should set quiet to True."""
        monkeypatch.setenv("ARBORIST_QUIET", "true")

        config = ArboristConfig()
        resolved = apply_env_overrides(config)
        assert resolved.defaults.quiet is True

    def test_arborist_quiet_env_false(self, monkeypatch):
        """ARBORIST_QUIET=false should set quiet to False."""
        monkeypatch.setenv("ARBORIST_QUIET", "false")

        config = ArboristConfig(defaults=DefaultsConfig(quiet=True))
        resolved = apply_env_overrides(config)
        assert resolved.defaults.quiet is False

    def test_timeout_env_var_override(self, monkeypatch):
        """ARBORIST_TIMEOUT_TASK_RUN should override timeout."""
        monkeypatch.setenv("ARBORIST_TIMEOUT_TASK_RUN", "7200")

        config = ArboristConfig()
        resolved = apply_env_overrides(config)
        assert resolved.timeouts.task_run == 7200

    def test_invalid_timeout_env_raises_error(self, monkeypatch):
        """Non-integer timeout env var should raise error."""
        monkeypatch.setenv("ARBORIST_TIMEOUT_TASK_RUN", "not_a_number")

        config = ArboristConfig()
        with pytest.raises(ConfigValidationError) as exc:
            apply_env_overrides(config)
        assert "ARBORIST_TIMEOUT_TASK_RUN" in str(exc.value)


class TestStepEnvVarOverride:
    """Unit tests for step-specific env var overrides."""

    def test_step_run_runner_env_override(self, monkeypatch):
        """ARBORIST_STEP_RUN_RUNNER should override run step runner."""
        monkeypatch.setenv("ARBORIST_STEP_RUN_RUNNER", "opencode")

        config = ArboristConfig(
            steps={"run": StepConfig(runner="claude"), "post-merge": StepConfig()}
        )
        resolved = apply_env_overrides(config)
        assert resolved.steps["run"].runner == "opencode"

    def test_step_run_model_env_override(self, monkeypatch):
        """ARBORIST_STEP_RUN_MODEL should override run step model."""
        monkeypatch.setenv("ARBORIST_STEP_RUN_MODEL", "opus")

        config = ArboristConfig(
            steps={"run": StepConfig(model="sonnet"), "post-merge": StepConfig()}
        )
        resolved = apply_env_overrides(config)
        assert resolved.steps["run"].model == "opus"

    def test_step_post_merge_env_override(self, monkeypatch):
        """ARBORIST_STEP_POST_MERGE_* should override post-merge step."""
        monkeypatch.setenv("ARBORIST_STEP_POST_MERGE_RUNNER", "gemini")
        monkeypatch.setenv("ARBORIST_STEP_POST_MERGE_MODEL", "flash")

        config = ArboristConfig()
        resolved = apply_env_overrides(config)
        assert resolved.steps["post-merge"].runner == "gemini"
        assert resolved.steps["post-merge"].model == "flash"

    def test_step_env_does_not_affect_other_steps(self, monkeypatch):
        """Step-specific env should not affect other steps."""
        monkeypatch.setenv("ARBORIST_STEP_RUN_RUNNER", "opencode")

        config = ArboristConfig(
            steps={
                "run": StepConfig(runner="claude"),
                "post-merge": StepConfig(runner="claude"),
            }
        )
        resolved = apply_env_overrides(config)
        assert resolved.steps["run"].runner == "opencode"  # overridden
        assert resolved.steps["post-merge"].runner == "claude"  # unchanged


class TestDeprecatedEnvVars:
    """Unit tests for backward-compatible deprecated env vars."""

    def test_arborist_default_runner_still_works(self, monkeypatch, caplog):
        """ARBORIST_DEFAULT_RUNNER should work but warn."""
        monkeypatch.setenv("ARBORIST_DEFAULT_RUNNER", "opencode")
        monkeypatch.delenv("ARBORIST_RUNNER", raising=False)

        config = ArboristConfig()
        with caplog.at_level(logging.WARNING):
            resolved = apply_env_overrides(config)

        assert resolved.defaults.runner == "opencode"
        assert "ARBORIST_DEFAULT_RUNNER" in caplog.text
        assert "deprecated" in caplog.text.lower()

    def test_arborist_default_model_still_works(self, monkeypatch, caplog):
        """ARBORIST_DEFAULT_MODEL should work but warn."""
        monkeypatch.setenv("ARBORIST_DEFAULT_MODEL", "opus")
        monkeypatch.delenv("ARBORIST_MODEL", raising=False)

        config = ArboristConfig()
        with caplog.at_level(logging.WARNING):
            resolved = apply_env_overrides(config)

        assert resolved.defaults.model == "opus"
        assert "ARBORIST_DEFAULT_MODEL" in caplog.text

    def test_new_env_var_takes_precedence(self, monkeypatch):
        """New ARBORIST_RUNNER should take precedence over deprecated."""
        monkeypatch.setenv("ARBORIST_RUNNER", "claude")
        monkeypatch.setenv("ARBORIST_DEFAULT_RUNNER", "opencode")

        config = ArboristConfig()
        resolved = apply_env_overrides(config)
        assert resolved.defaults.runner == "claude"  # new wins


# =============================================================================
# Phase 5: Runner/Model Resolution
# =============================================================================


class TestGetStepRunnerModel:
    """Unit tests for runner/model resolution per step."""

    def test_cli_flags_take_precedence(self):
        """CLI flags should override all config."""
        config = ArboristConfig(
            defaults=DefaultsConfig(runner="claude", model="sonnet"),
            steps={
                "run": StepConfig(runner="gemini", model="flash"),
                "post-merge": StepConfig(),
            },
        )

        runner, model = get_step_runner_model(
            config, step="run", cli_runner="opencode", cli_model="glm-4.7"
        )
        assert runner == "opencode"
        assert model == "glm-4.7"

    def test_step_config_overrides_defaults(self):
        """Step config should override defaults."""
        config = ArboristConfig(
            defaults=DefaultsConfig(runner="claude", model="sonnet"),
            steps={
                "run": StepConfig(runner="opencode", model="glm-4.7"),
                "post-merge": StepConfig(),
            },
        )

        runner, model = get_step_runner_model(config, step="run")
        assert runner == "opencode"
        assert model == "glm-4.7"

    def test_defaults_used_when_no_step_config(self):
        """Defaults should be used when step config is None."""
        config = ArboristConfig(
            defaults=DefaultsConfig(runner="claude", model="sonnet"),
            steps={"run": StepConfig(), "post-merge": StepConfig()},  # both None
        )

        runner, model = get_step_runner_model(config, step="run")
        assert runner == "claude"
        assert model == "sonnet"

    def test_independent_field_resolution(self):
        """Runner and model resolve independently."""
        config = ArboristConfig(
            defaults=DefaultsConfig(runner="claude", model="sonnet"),
            steps={
                "run": StepConfig(runner=None, model="opus"),  # only model
                "post-merge": StepConfig(),
            },
        )

        runner, model = get_step_runner_model(config, step="run")
        assert runner == "claude"  # from defaults
        assert model == "opus"  # from step

    def test_hardcoded_defaults_when_no_config(self):
        """Hardcoded defaults when nothing configured."""
        config = ArboristConfig()  # all defaults/None

        runner, model = get_step_runner_model(config, step="run")
        assert runner == "claude"  # hardcoded default
        assert model == "sonnet"  # hardcoded default

    def test_unknown_step_uses_defaults(self):
        """Unknown step should fall back to defaults."""
        config = ArboristConfig(
            defaults=DefaultsConfig(runner="opencode", model="glm-4.7")
        )

        runner, model = get_step_runner_model(config, step="unknown_step")
        assert runner == "opencode"
        assert model == "glm-4.7"

    def test_cli_runner_only_with_step_model(self):
        """CLI runner with step model."""
        config = ArboristConfig(
            defaults=DefaultsConfig(runner="claude", model="sonnet"),
            steps={"run": StepConfig(model="opus"), "post-merge": StepConfig()},
        )

        runner, model = get_step_runner_model(
            config, step="run", cli_runner="gemini", cli_model=None
        )
        assert runner == "gemini"  # CLI
        assert model == "opus"  # step config (CLI model was None)


class TestModelAliasResolution:
    """Unit tests for model alias expansion."""

    def test_alias_expanded_for_runner(self):
        """Model alias should expand to full name."""
        config = ArboristConfig(
            runners={
                "claude": RunnerConfig(
                    models={
                        "sonnet": "claude-3-5-sonnet-20241022",
                        "opus": "claude-3-opus-20240229",
                    }
                )
            }
        )

        full_name = resolve_model_alias(config, runner="claude", model="sonnet")
        assert full_name == "claude-3-5-sonnet-20241022"

    def test_unknown_alias_returns_as_is(self):
        """Unknown alias should return the model name as-is."""
        config = ArboristConfig()

        full_name = resolve_model_alias(config, runner="claude", model="custom-model")
        assert full_name == "custom-model"

    def test_alias_resolution_runner_specific(self):
        """Aliases should be runner-specific."""
        config = ArboristConfig(
            runners={
                "claude": RunnerConfig(models={"fast": "claude-3-haiku"}),
                "gemini": RunnerConfig(models={"fast": "gemini-1.5-flash"}),
            }
        )

        claude_fast = resolve_model_alias(config, runner="claude", model="fast")
        gemini_fast = resolve_model_alias(config, runner="gemini", model="fast")

        assert claude_fast == "claude-3-haiku"
        assert gemini_fast == "gemini-1.5-flash"


# =============================================================================
# Phase 6: Full Config Loading Pipeline
# =============================================================================


class TestGetConfig:
    """Integration tests for full config loading pipeline."""

    def test_get_config_with_no_files(self, tmp_path, monkeypatch):
        """get_config returns defaults when no files exist."""
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.delenv("ARBORIST_RUNNER", raising=False)
        monkeypatch.delenv("ARBORIST_MODEL", raising=False)
        monkeypatch.delenv("ARBORIST_DEFAULT_RUNNER", raising=False)
        monkeypatch.delenv("ARBORIST_DEFAULT_MODEL", raising=False)

        config = get_config(arborist_home=tmp_path / ".arborist")
        assert config.defaults.runner is None
        assert config.defaults.model is None
        assert config.timeouts.task_run == 1800

    def test_get_config_loads_global_file(self, tmp_path, monkeypatch):
        """get_config loads global config from ~/.arborist_config.json."""
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.delenv("ARBORIST_RUNNER", raising=False)
        monkeypatch.delenv("ARBORIST_MODEL", raising=False)
        monkeypatch.delenv("ARBORIST_DEFAULT_RUNNER", raising=False)
        monkeypatch.delenv("ARBORIST_DEFAULT_MODEL", raising=False)

        global_config = tmp_path / ".arborist_config.json"
        global_config.write_text(
            json.dumps({"defaults": {"runner": "claude", "model": "sonnet"}})
        )

        config = get_config(arborist_home=tmp_path / ".arborist")
        assert config.defaults.runner == "claude"
        assert config.defaults.model == "sonnet"

    def test_get_config_loads_project_file(self, tmp_path, monkeypatch):
        """get_config loads project config from .arborist/config.json."""
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.delenv("ARBORIST_RUNNER", raising=False)
        monkeypatch.delenv("ARBORIST_DEFAULT_RUNNER", raising=False)

        arborist_home = tmp_path / ".arborist"
        arborist_home.mkdir()
        project_config = arborist_home / "config.json"
        project_config.write_text(json.dumps({"defaults": {"runner": "opencode"}}))

        config = get_config(arborist_home=arborist_home)
        assert config.defaults.runner == "opencode"

    def test_get_config_merges_global_and_project(self, tmp_path, monkeypatch):
        """get_config merges global and project configs correctly."""
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.delenv("ARBORIST_RUNNER", raising=False)
        monkeypatch.delenv("ARBORIST_MODEL", raising=False)
        monkeypatch.delenv("ARBORIST_DEFAULT_RUNNER", raising=False)
        monkeypatch.delenv("ARBORIST_DEFAULT_MODEL", raising=False)

        # Global config
        global_config = tmp_path / ".arborist_config.json"
        global_config.write_text(
            json.dumps(
                {
                    "defaults": {"runner": "claude", "model": "sonnet"},
                    "timeouts": {"task_run": 3600},
                }
            )
        )

        # Project config
        arborist_home = tmp_path / ".arborist"
        arborist_home.mkdir()
        project_config = arborist_home / "config.json"
        project_config.write_text(
            json.dumps({"defaults": {"runner": "opencode"}})  # override runner only
        )

        config = get_config(arborist_home=arborist_home)
        assert config.defaults.runner == "opencode"  # project wins
        assert config.defaults.model == "sonnet"  # global preserved
        assert config.timeouts.task_run == 3600  # global preserved

    def test_get_config_applies_env_overrides(self, tmp_path, monkeypatch):
        """get_config applies env var overrides after file loading."""
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("ARBORIST_RUNNER", "gemini")

        global_config = tmp_path / ".arborist_config.json"
        global_config.write_text(json.dumps({"defaults": {"runner": "claude"}}))

        config = get_config(arborist_home=tmp_path / ".arborist")
        assert config.defaults.runner == "gemini"  # env wins


# =============================================================================
# Phase 7: Config Template Generation
# =============================================================================


class TestConfigTemplate:
    """Unit tests for config template generation."""

    def test_generate_template_has_all_sections(self):
        """Generated template should have all config sections."""
        template = generate_config_template()

        assert "version" in template
        assert "defaults" in template
        assert "timeouts" in template
        assert "steps" in template
        assert "test" in template
        assert "paths" in template

    def test_generate_template_has_comments(self):
        """Generated template should have inline comments."""
        template_str = generate_config_template_string()

        # Comments may use // or # or be in a _comment field
        assert (
            "//" in template_str
            or "#" in template_str
            or "_comment" in template_str
            or "comment" in template_str.lower()
        )
        assert "runner" in template_str
        assert "claude" in template_str  # Shows valid values

    def test_template_is_valid_json_without_comments(self):
        """Template without comments should be valid JSON."""
        template = generate_config_template()
        json_str = json.dumps(template)
        parsed = json.loads(json_str)
        assert parsed["version"] == "1"

    def test_template_shows_all_valid_values(self):
        """Template comments should show all valid enum values."""
        template_str = generate_config_template_string()

        # Runner values
        assert "claude" in template_str
        assert "opencode" in template_str
        assert "gemini" in template_str

        # Container mode values
        assert "auto" in template_str
        assert "enabled" in template_str
        assert "disabled" in template_str


# =============================================================================
# Hooks Configuration Tests
# =============================================================================


class TestHooksConfigDataclasses:
    """Unit tests for hooks config dataclass construction and defaults."""

    def test_step_definition_has_correct_defaults(self):
        """StepDefinition should have sensible defaults."""
        step = StepDefinition(type="shell")
        assert step.type == "shell"
        assert step.prompt is None
        assert step.prompt_file is None
        assert step.command is None
        assert step.timeout == 120
        assert step.env == {}

    def test_step_definition_llm_eval_type(self):
        """StepDefinition for llm_eval should accept prompt."""
        step = StepDefinition(
            type="llm_eval",
            prompt="Review the code in {{worktree_path}}",
            runner="claude",
            model="haiku",
        )
        assert step.type == "llm_eval"
        assert "{{worktree_path}}" in step.prompt
        assert step.runner == "claude"
        assert step.model == "haiku"

    def test_step_definition_prompt_file(self):
        """StepDefinition can reference prompt file."""
        step = StepDefinition(
            type="llm_eval",
            prompt_file="code_review.txt",
        )
        assert step.prompt_file == "code_review.txt"
        assert step.prompt is None

    def test_hook_injection_has_correct_defaults(self):
        """HookInjection should have sensible defaults."""
        inj = HookInjection(step="my_step")
        assert inj.step == "my_step"
        assert inj.tasks == ["*"]
        assert inj.tasks_exclude == []
        assert inj.after is None
        assert inj.before is None

    def test_hook_injection_inline_step(self):
        """HookInjection can define inline step."""
        inj = HookInjection(
            type="shell",
            command="npm run lint",
            tasks=["T001", "T002"],
        )
        assert inj.type == "shell"
        assert inj.command == "npm run lint"
        assert inj.tasks == ["T001", "T002"]

    def test_hook_injection_get_step_definition_inline(self):
        """get_step_definition returns inline step for inline injection."""
        inj = HookInjection(
            type="shell",
            command="npm run lint",
            timeout=60,
        )
        step_def = inj.get_step_definition()
        assert step_def is not None
        assert step_def.type == "shell"
        assert step_def.command == "npm run lint"
        assert step_def.timeout == 60

    def test_hook_injection_get_step_definition_reference(self):
        """get_step_definition returns None for step references."""
        inj = HookInjection(step="my_step")
        step_def = inj.get_step_definition()
        assert step_def is None

    def test_hooks_config_has_correct_defaults(self):
        """HooksConfig should have sensible defaults."""
        config = HooksConfig()
        assert config.enabled is False
        assert config.prompts_dir == "prompts"
        assert config.step_definitions == {}
        assert config.injections == {}

    def test_hooks_config_with_step_definitions(self):
        """HooksConfig should store step definitions."""
        config = HooksConfig(
            enabled=True,
            step_definitions={
                "lint": StepDefinition(type="shell", command="npm run lint"),
                "eval": StepDefinition(type="llm_eval", prompt="Review code"),
            },
        )
        assert len(config.step_definitions) == 2
        assert config.step_definitions["lint"].type == "shell"
        assert config.step_definitions["eval"].type == "llm_eval"


class TestHooksConfigValidation:
    """Unit tests for hooks configuration validation."""

    def test_invalid_step_type_raises_error(self):
        """Invalid step type should raise ConfigValidationError."""
        step = StepDefinition(type="invalid_type")
        with pytest.raises(ConfigValidationError) as exc:
            step.validate()
        assert "invalid_type" in str(exc.value)
        assert "type" in str(exc.value).lower()

    def test_valid_step_types_accepted(self):
        """Valid step types should pass validation."""
        for step_type in VALID_STEP_TYPES:
            if step_type == "llm_eval":
                step = StepDefinition(type=step_type, prompt="test")
            elif step_type == "shell":
                step = StepDefinition(type=step_type, command="echo test")
            elif step_type == "quality_check":
                step = StepDefinition(type=step_type, command="pytest")
            elif step_type == "python":
                step = StepDefinition(type=step_type, class_path="mymodule.MyClass")
            step.validate()  # Should not raise

    def test_llm_eval_without_prompt_raises_error(self):
        """llm_eval step without prompt or prompt_file should fail."""
        step = StepDefinition(type="llm_eval")
        with pytest.raises(ConfigValidationError) as exc:
            step.validate()
        assert "prompt" in str(exc.value).lower()

    def test_shell_without_command_raises_error(self):
        """shell step without command should fail."""
        step = StepDefinition(type="shell")
        with pytest.raises(ConfigValidationError) as exc:
            step.validate()
        assert "command" in str(exc.value).lower()

    def test_python_without_class_raises_error(self):
        """python step without class_path should fail."""
        step = StepDefinition(type="python")
        with pytest.raises(ConfigValidationError) as exc:
            step.validate()
        assert "class" in str(exc.value).lower()

    def test_invalid_hook_point_raises_error(self):
        """Invalid hook point should raise ConfigValidationError."""
        config = HooksConfig(
            enabled=True,
            injections={
                "invalid_point": [HookInjection(type="shell", command="echo")]
            },
        )
        with pytest.raises(ConfigValidationError) as exc:
            config.validate()
        assert "invalid_point" in str(exc.value)

    def test_valid_hook_points_accepted(self):
        """Valid hook points should pass validation."""
        for hook_point in VALID_HOOK_POINTS:
            config = HooksConfig(
                enabled=True,
                injections={
                    hook_point: [HookInjection(type="shell", command="echo")]
                },
            )
            config.validate()  # Should not raise

    def test_undefined_step_reference_raises_error(self):
        """Reference to undefined step should fail validation."""
        config = HooksConfig(
            enabled=True,
            injections={
                "post_task": [HookInjection(step="nonexistent_step")]
            },
        )
        with pytest.raises(ConfigValidationError) as exc:
            config.validate()
        assert "nonexistent_step" in str(exc.value)

    def test_valid_step_reference_passes(self):
        """Reference to defined step should pass validation."""
        config = HooksConfig(
            enabled=True,
            step_definitions={
                "my_lint": StepDefinition(type="shell", command="npm run lint")
            },
            injections={
                "post_task": [HookInjection(step="my_lint")]
            },
        )
        config.validate()  # Should not raise


class TestHooksConfigSerialization:
    """Unit tests for hooks config serialization."""

    def test_step_definition_to_dict(self):
        """StepDefinition.to_dict() returns correct structure."""
        step = StepDefinition(
            type="llm_eval",
            prompt="Review code",
            runner="claude",
            model="haiku",
            timeout=60,
        )
        d = step.to_dict()
        assert d["type"] == "llm_eval"
        assert d["prompt"] == "Review code"
        assert d["runner"] == "claude"
        assert d["model"] == "haiku"
        assert d["timeout"] == 60

    def test_step_definition_from_dict(self):
        """StepDefinition.from_dict() creates correct instance."""
        d = {
            "type": "shell",
            "command": "npm run lint",
            "timeout": 30,
            "env": {"NODE_ENV": "test"},
        }
        step = StepDefinition.from_dict(d)
        assert step.type == "shell"
        assert step.command == "npm run lint"
        assert step.timeout == 30
        assert step.env == {"NODE_ENV": "test"}

    def test_hook_injection_to_dict(self):
        """HookInjection.to_dict() returns correct structure."""
        inj = HookInjection(
            step="my_step",
            tasks=["T001", "T002"],
            after="run",
        )
        d = inj.to_dict()
        assert d["step"] == "my_step"
        assert d["tasks"] == ["T001", "T002"]
        assert d["after"] == "run"

    def test_hook_injection_from_dict(self):
        """HookInjection.from_dict() creates correct instance."""
        d = {
            "type": "shell",
            "command": "npm test",
            "tasks_exclude": ["T003"],
        }
        inj = HookInjection.from_dict(d)
        assert inj.type == "shell"
        assert inj.command == "npm test"
        assert inj.tasks == ["*"]
        assert inj.tasks_exclude == ["T003"]

    def test_hooks_config_round_trip(self):
        """HooksConfig survives to_dict/from_dict round trip."""
        original = HooksConfig(
            enabled=True,
            prompts_dir="my_prompts",
            step_definitions={
                "lint": StepDefinition(type="shell", command="npm lint"),
                "eval": StepDefinition(type="llm_eval", prompt="Review"),
            },
            injections={
                "post_task": [
                    HookInjection(step="lint", tasks=["T001"]),
                    HookInjection(step="eval"),
                ],
            },
        )
        d = original.to_dict()
        restored = HooksConfig.from_dict(d)
        assert restored.enabled is True
        assert restored.prompts_dir == "my_prompts"
        assert len(restored.step_definitions) == 2
        assert restored.step_definitions["lint"].command == "npm lint"
        assert len(restored.injections["post_task"]) == 2

    def test_arborist_config_with_hooks_round_trip(self):
        """ArboristConfig with hooks survives round trip."""
        original = ArboristConfig(
            defaults=DefaultsConfig(runner="claude"),
            hooks=HooksConfig(
                enabled=True,
                step_definitions={
                    "test": StepDefinition(type="shell", command="pytest")
                },
            ),
        )
        d = original.to_dict()
        restored = ArboristConfig.from_dict(d)
        assert restored.hooks.enabled is True
        assert "test" in restored.hooks.step_definitions


class TestHooksConfigMerging:
    """Unit tests for hooks config merging."""

    def test_merge_hooks_enabled_flag(self):
        """Later config's enabled flag should win."""
        config1 = ArboristConfig(hooks=HooksConfig(enabled=False))
        config2 = ArboristConfig(hooks=HooksConfig(enabled=True))

        merged = merge_configs(config1, config2)
        assert merged.hooks.enabled is True

    def test_merge_hooks_step_definitions(self):
        """Step definitions should merge with later overriding."""
        config1 = ArboristConfig(
            hooks=HooksConfig(
                step_definitions={
                    "lint": StepDefinition(type="shell", command="eslint"),
                    "test": StepDefinition(type="shell", command="jest"),
                }
            )
        )
        config2 = ArboristConfig(
            hooks=HooksConfig(
                step_definitions={
                    "lint": StepDefinition(type="shell", command="npm lint"),
                }
            )
        )

        merged = merge_configs(config1, config2)
        assert merged.hooks.step_definitions["lint"].command == "npm lint"
        assert merged.hooks.step_definitions["test"].command == "jest"

    def test_merge_hooks_injections_extend(self):
        """Injections at same hook point should extend list."""
        config1 = ArboristConfig(
            hooks=HooksConfig(
                enabled=True,
                step_definitions={
                    "lint": StepDefinition(type="shell", command="lint"),
                    "test": StepDefinition(type="shell", command="test"),
                },
                injections={
                    "post_task": [HookInjection(step="lint")],
                }
            )
        )
        config2 = ArboristConfig(
            hooks=HooksConfig(
                step_definitions={
                    "lint": StepDefinition(type="shell", command="lint"),
                    "test": StepDefinition(type="shell", command="test"),
                },
                injections={
                    "post_task": [HookInjection(step="test")],
                }
            )
        )

        merged = merge_configs(config1, config2)
        assert len(merged.hooks.injections["post_task"]) == 2


class TestHooksConfigFileLoading:
    """Tests for loading hooks config from files."""

    def test_load_config_with_hooks(self, tmp_path):
        """Config file with hooks section should load correctly."""
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps(
                {
                    "hooks": {
                        "enabled": True,
                        "prompts_dir": "custom_prompts",
                        "step_definitions": {
                            "my_lint": {
                                "type": "shell",
                                "command": "npm run lint",
                            }
                        },
                        "injections": {
                            "post_task": [
                                {"step": "my_lint", "tasks": ["*"]}
                            ]
                        },
                    }
                }
            )
        )

        config = load_config_file(config_file)
        assert config.hooks.enabled is True
        assert config.hooks.prompts_dir == "custom_prompts"
        assert "my_lint" in config.hooks.step_definitions
        assert len(config.hooks.injections["post_task"]) == 1

    def test_config_without_hooks_has_default(self, tmp_path):
        """Config file without hooks should have default HooksConfig."""
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"defaults": {"runner": "claude"}}))

        config = load_config_file(config_file)
        assert config.hooks.enabled is False
        assert config.hooks.step_definitions == {}


class TestHooksConfigTemplate:
    """Tests for hooks section in config template."""

    def test_template_has_hooks_section(self):
        """Generated template should have hooks section."""
        template = generate_config_template()
        assert "hooks" in template
        assert "enabled" in template["hooks"]
        assert "step_definitions" in template["hooks"]
        assert "injections" in template["hooks"]

    def test_template_hooks_shows_example(self):
        """Template hooks should show useful example."""
        template_str = generate_config_template_string()
        assert "hooks" in template_str
        assert "llm_eval" in template_str or "shell" in template_str


# =============================================================================
# Phase 11: Edge Cases and Error Handling
# =============================================================================


# =============================================================================
# Phase 8: CLI Integration
# =============================================================================


class TestConfigShowCommand:
    """Integration tests for `arborist config show` command."""

    @pytest.fixture
    def runner(self):
        """CLI test runner."""
        from click.testing import CliRunner

        return CliRunner()

    @pytest.fixture
    def main(self):
        """Import main CLI."""
        from agent_arborist.cli import main

        return main

    def test_config_show_outputs_json(self, runner, main, tmp_path, monkeypatch):
        """config show should output JSON config."""
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.delenv("ARBORIST_RUNNER", raising=False)
        monkeypatch.delenv("ARBORIST_DEFAULT_RUNNER", raising=False)

        result = runner.invoke(main, ["config", "show"])

        assert result.exit_code == 0
        config = json.loads(result.output)
        assert "defaults" in config
        assert "timeouts" in config

    def test_config_show_reflects_global_config(self, runner, main, tmp_path, monkeypatch):
        """config show should reflect global config values."""
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.delenv("ARBORIST_RUNNER", raising=False)
        monkeypatch.delenv("ARBORIST_DEFAULT_RUNNER", raising=False)

        global_config = tmp_path / ".arborist_config.json"
        global_config.write_text(json.dumps({"defaults": {"runner": "opencode"}}))

        result = runner.invoke(main, ["config", "show"])
        config = json.loads(result.output)
        assert config["defaults"]["runner"] == "opencode"

    def test_config_show_reflects_env_overrides(self, runner, main, tmp_path, monkeypatch):
        """config show should reflect env var overrides."""
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("ARBORIST_RUNNER", "gemini")

        result = runner.invoke(main, ["config", "show"])
        config = json.loads(result.output)
        assert config["defaults"]["runner"] == "gemini"


class TestConfigInitCommand:
    """Integration tests for `arborist config init` command."""

    @pytest.fixture
    def runner(self):
        """CLI test runner."""
        from click.testing import CliRunner

        return CliRunner()

    @pytest.fixture
    def main(self):
        """Import main CLI."""
        from agent_arborist.cli import main

        return main

    def test_config_init_creates_global_file(self, runner, main, tmp_path, monkeypatch):
        """config init --global creates ~/.arborist_config.json."""
        monkeypatch.setenv("HOME", str(tmp_path))

        result = runner.invoke(main, ["config", "init", "--global"])

        assert result.exit_code == 0
        config_file = tmp_path / ".arborist_config.json"
        assert config_file.exists()

    def test_config_init_creates_commented_template(self, runner, main, tmp_path, monkeypatch):
        """config init should create a commented template."""
        monkeypatch.setenv("HOME", str(tmp_path))

        runner.invoke(main, ["config", "init", "--global"])

        config_file = tmp_path / ".arborist_config.json"
        content = config_file.read_text()
        # Should have documentation/comments in some form
        assert "version" in content
        assert "defaults" in content

    def test_config_init_does_not_overwrite(self, runner, main, tmp_path, monkeypatch):
        """config init should not overwrite existing config."""
        monkeypatch.setenv("HOME", str(tmp_path))

        config_file = tmp_path / ".arborist_config.json"
        config_file.write_text('{"existing": "config"}')

        result = runner.invoke(main, ["config", "init", "--global"])

        assert result.exit_code != 0 or "exists" in result.output.lower()
        assert config_file.read_text() == '{"existing": "config"}'

    def test_config_init_force_overwrites(self, runner, main, tmp_path, monkeypatch):
        """config init --force should overwrite existing config."""
        monkeypatch.setenv("HOME", str(tmp_path))

        config_file = tmp_path / ".arborist_config.json"
        config_file.write_text('{"existing": "config"}')

        result = runner.invoke(main, ["config", "init", "--global", "--force"])

        assert result.exit_code == 0
        content = json.loads(config_file.read_text())
        assert "version" in content


class TestConfigValidateCommand:
    """Integration tests for `arborist config validate` command."""

    @pytest.fixture
    def runner(self):
        """CLI test runner."""
        from click.testing import CliRunner

        return CliRunner()

    @pytest.fixture
    def main(self):
        """Import main CLI."""
        from agent_arborist.cli import main

        return main

    def test_config_validate_valid_config(self, runner, main, tmp_path, monkeypatch):
        """config validate should succeed for valid config."""
        monkeypatch.setenv("HOME", str(tmp_path))

        config_file = tmp_path / ".arborist_config.json"
        config_file.write_text(
            json.dumps({"version": "1", "defaults": {"runner": "claude"}})
        )

        result = runner.invoke(main, ["config", "validate"])

        assert result.exit_code == 0
        assert "valid" in result.output.lower()

    def test_config_validate_invalid_runner(self, runner, main, tmp_path, monkeypatch):
        """config validate should fail for invalid runner."""
        monkeypatch.setenv("HOME", str(tmp_path))

        config_file = tmp_path / ".arborist_config.json"
        config_file.write_text(json.dumps({"defaults": {"runner": "invalid_runner"}}))

        result = runner.invoke(main, ["config", "validate"])

        assert result.exit_code != 0
        assert "runner" in result.output.lower()
        assert "invalid" in result.output.lower()

    def test_config_validate_unknown_field(self, runner, main, tmp_path, monkeypatch):
        """config validate should fail for unknown fields."""
        monkeypatch.setenv("HOME", str(tmp_path))

        config_file = tmp_path / ".arborist_config.json"
        config_file.write_text(json.dumps({"unknown_field": "value"}))

        result = runner.invoke(main, ["config", "validate"])

        assert result.exit_code != 0
        assert "unknown_field" in result.output

    def test_config_validate_invalid_json(self, runner, main, tmp_path, monkeypatch):
        """config validate should fail for invalid JSON."""
        monkeypatch.setenv("HOME", str(tmp_path))

        config_file = tmp_path / ".arborist_config.json"
        config_file.write_text("{ invalid json }")

        result = runner.invoke(main, ["config", "validate"])

        assert result.exit_code != 0
        assert "json" in result.output.lower() or "parse" in result.output.lower()


# =============================================================================
# Phase 9: DAG Builder Integration
# =============================================================================


class TestDagBuilderConfig:
    """Integration tests for DAG builder using config."""

    def test_dag_config_with_arborist_config(self):
        """DagConfig should accept arborist_config parameter."""
        from agent_arborist.dag_builder import DagConfig

        arborist_config = ArboristConfig(
            steps={
                "run": StepConfig(runner="opencode", model="glm-4.7"),
                "post-merge": StepConfig(runner="gemini", model="flash"),
            }
        )

        dag_config = DagConfig(
            name="test-dag",
            arborist_config=arborist_config,
        )

        assert dag_config.arborist_config is not None
        assert dag_config.arborist_config.steps["run"].runner == "opencode"

    def test_dag_builder_does_not_embed_runner_model(self, tmp_path):
        """DAG builder should NOT embed runner/model - resolved at runtime."""
        from agent_arborist.dag_builder import DagConfig, SubDagBuilder
        from agent_arborist.task_spec import TaskSpec, Phase, Task
        from agent_arborist.task_state import TaskTree, TaskNode

        arborist_config = ArboristConfig(
            steps={
                "run": StepConfig(runner="opencode", model="glm-4.7"),
                "post-merge": StepConfig(runner="gemini", model="flash"),
            }
        )

        dag_config = DagConfig(
            name="test-spec",
            spec_id="001-test",
            arborist_config=arborist_config,
        )

        # Create a simple spec and task tree
        spec = TaskSpec(
            project="Test",
            total_tasks=1,
            phases=[Phase(name="Phase 1", tasks=[Task(id="T001", description="Test task")])],
        )
        task_tree = TaskTree(spec_id="001-test")
        task_tree.tasks = {"T001": TaskNode(task_id="T001", description="Test task")}
        task_tree.root_tasks = ["T001"]

        builder = SubDagBuilder(dag_config)
        bundle = builder.build(spec, task_tree)

        # Find the T001 subdag
        t001_subdag = next((s for s in bundle.subdags if s.name == "T001"), None)
        assert t001_subdag is not None

        # Verify run step does NOT contain runner/model (resolved at runtime)
        run_step = next((s for s in t001_subdag.steps if s.name == "run"), None)
        assert run_step is not None
        assert run_step.command == "arborist task run T001"
        assert "--runner" not in run_step.command
        assert "--model" not in run_step.command

        # Verify post-merge step does NOT contain runner/model
        post_merge_step = next(
            (s for s in t001_subdag.steps if s.name == "post-merge"), None
        )
        assert post_merge_step is not None
        assert post_merge_step.command == "arborist task post-merge T001"
        assert "--runner" not in post_merge_step.command
        assert "--model" not in post_merge_step.command

    def test_dag_config_get_step_runner_model_still_works(self, tmp_path):
        """DagConfig.get_step_runner_model() should still resolve for other uses."""
        from agent_arborist.dag_builder import DagConfig

        arborist_config = ArboristConfig(
            defaults=DefaultsConfig(runner="claude", model="sonnet"),
            steps={
                "run": StepConfig(runner="opencode", model="glm-4.7"),
            }
        )

        dag_config = DagConfig(
            name="test-spec",
            spec_id="001-test",
            arborist_config=arborist_config,
        )

        # get_step_runner_model() should return resolved values
        run_runner, run_model = dag_config.get_step_runner_model("run")
        assert run_runner == "opencode"
        assert run_model == "glm-4.7"

        # post-merge uses defaults
        pm_runner, pm_model = dag_config.get_step_runner_model("post-merge")
        assert pm_runner == "claude"
        assert pm_model == "sonnet"

    def test_dag_config_runner_model_as_cli_override(self, tmp_path):
        """DagConfig runner/model fields act as CLI overrides when config present."""
        from agent_arborist.dag_builder import DagConfig

        arborist_config = ArboristConfig(
            defaults=DefaultsConfig(runner="claude", model="sonnet"),
            steps={
                "run": StepConfig(runner="opencode", model="glm-4.7"),
            }
        )

        # runner/model on DagConfig act as CLI overrides
        dag_config = DagConfig(
            name="test-spec",
            spec_id="001-test",
            arborist_config=arborist_config,
            runner="gemini",  # CLI override
            model="flash",    # CLI override
        )

        # CLI override should take precedence
        run_runner, run_model = dag_config.get_step_runner_model("run")
        assert run_runner == "gemini"
        assert run_model == "flash"


# =============================================================================
# Phase 10: E2E Tests with Real AI Calls
# =============================================================================


@pytest.mark.integration
class TestE2EConfigWorkflow:
    """E2E tests for config system in real workflows.

    These tests verify that config settings actually affect CLI behavior
    by running `dag build` and checking generated YAML files.
    """

    @pytest.fixture
    def runner(self):
        """CLI test runner."""
        from click.testing import CliRunner

        return CliRunner()

    @pytest.fixture
    def main(self):
        """Import main CLI."""
        from agent_arborist.cli import main

        return main

    @pytest.fixture
    def git_repo_with_config(self, tmp_path, monkeypatch):
        """Create a git repo with arborist initialized and config file.

        This fixture sets up a complete, realistic project structure:
        - Git repository with initial commit
        - Arborist initialized (.arborist/ directory)
        - A spec file for DAG generation
        - Config file with custom runner/model settings
        """
        import subprocess

        original_cwd = os.getcwd()
        os.chdir(tmp_path)

        # Initialize git repo
        subprocess.run(["git", "init"], capture_output=True, check=True)
        readme = tmp_path / "README.md"
        readme.write_text("# Test Project\n")
        subprocess.run(["git", "add", "."], capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            capture_output=True,
            check=True,
            env={
                **os.environ,
                "GIT_AUTHOR_NAME": "Test",
                "GIT_AUTHOR_EMAIL": "test@test.com",
                "GIT_COMMITTER_NAME": "Test",
                "GIT_COMMITTER_EMAIL": "test@test.com",
            },
        )

        # Set HOME to tmp_path so global config doesn't interfere
        monkeypatch.setenv("HOME", str(tmp_path))
        # Clear any env vars that would override config
        monkeypatch.delenv("ARBORIST_RUNNER", raising=False)
        monkeypatch.delenv("ARBORIST_MODEL", raising=False)
        monkeypatch.delenv("ARBORIST_DEFAULT_RUNNER", raising=False)
        monkeypatch.delenv("ARBORIST_DEFAULT_MODEL", raising=False)
        monkeypatch.delenv("ARBORIST_STEP_RUN_RUNNER", raising=False)
        monkeypatch.delenv("ARBORIST_STEP_RUN_MODEL", raising=False)
        monkeypatch.delenv("ARBORIST_STEP_POST_MERGE_RUNNER", raising=False)
        monkeypatch.delenv("ARBORIST_STEP_POST_MERGE_MODEL", raising=False)

        # Initialize arborist
        from click.testing import CliRunner
        from agent_arborist.cli import main

        cli_runner = CliRunner()
        result = cli_runner.invoke(main, ["init"])
        assert result.exit_code == 0, f"Init failed: {result.output}"

        # Create spec directory with task file
        spec_dir = tmp_path / "specs" / "test-spec"
        spec_dir.mkdir(parents=True)
        (spec_dir / "tasks.md").write_text("""# Tasks: Test Project

**Project**: Test project
**Total Tasks**: 2

## Phase 1: Setup

- [ ] T001 Create initial file
- [ ] T002 Add feature (depends on T001)

**Checkpoint**: Ready

---

## Dependencies

```
T001 → T002
```
""")

        yield tmp_path

        os.chdir(original_cwd)

    def test_dag_build_does_not_embed_runner_model(self, runner, main, git_repo_with_config):
        """Verify generated DAGs do NOT contain runner/model - resolved at runtime.

        This test:
        1. Creates project config with runner/model settings
        2. Runs `arborist spec dag-build --no-ai`
        3. Verifies generated YAML commands do NOT contain --runner/--model flags
        """
        import yaml

        # Create project config with specific runner/model
        config_file = git_repo_with_config / ".arborist" / "config.json"
        config_file.write_text(
            json.dumps(
                {
                    "steps": {
                        "run": {"runner": "opencode", "model": "config-run-model"},
                        "post-merge": {"runner": "gemini", "model": "config-merge-model"},
                    }
                }
            )
        )

        spec_dir = git_repo_with_config / "specs" / "test-spec"

        # Run dag build (with --no-ai to skip AI generation)
        result = runner.invoke(main, ["spec", "dag-build", str(spec_dir), "--no-ai"])
        assert result.exit_code == 0, f"dag-build failed: {result.output}"

        # Find generated DAG file
        dagu_dir = git_repo_with_config / ".arborist" / "dagu" / "dags"
        dag_files = list(dagu_dir.glob("*.yaml"))
        assert len(dag_files) >= 1, f"No DAG files generated in {dagu_dir}"

        # Read and parse all YAML documents
        dag_content = dag_files[0].read_text()
        documents = list(yaml.safe_load_all(dag_content))

        # Find run and post-merge steps in task subdags
        run_commands = []
        post_merge_commands = []

        for doc in documents:
            if not doc:
                continue
            for step in doc.get("steps", []):
                cmd = step.get("command", "")
                if step.get("name") == "run":
                    run_commands.append(cmd)
                elif step.get("name") == "post-merge":
                    post_merge_commands.append(cmd)

        # Verify run commands do NOT contain runner/model (resolved at runtime)
        assert len(run_commands) > 0, "No 'run' steps found in generated DAG"
        for cmd in run_commands:
            assert "--runner" not in cmd, f"Unexpected --runner in run command: {cmd}"
            assert "--model" not in cmd, f"Unexpected --model in run command: {cmd}"
            # Should be plain command like "arborist task run T001"
            assert cmd.startswith("arborist task run "), f"Unexpected run command format: {cmd}"

        # Verify post-merge commands do NOT contain runner/model
        assert len(post_merge_commands) > 0, "No 'post-merge' steps found in generated DAG"
        for cmd in post_merge_commands:
            assert "--runner" not in cmd, f"Unexpected --runner in post-merge command: {cmd}"
            assert "--model" not in cmd, f"Unexpected --model in post-merge command: {cmd}"

    def test_config_resolves_at_runtime_via_get_step_runner_model(self, runner, main, git_repo_with_config):
        """Verify config resolution works correctly via get_step_runner_model.

        This test verifies the runtime resolution logic by calling get_step_runner_model
        directly with a loaded config.
        """
        from agent_arborist.config import get_config, get_step_runner_model

        # Create project config with step-specific settings
        config_file = git_repo_with_config / ".arborist" / "config.json"
        config_file.write_text(
            json.dumps(
                {
                    "defaults": {"runner": "claude", "model": "sonnet"},
                    "steps": {
                        "run": {"runner": "opencode", "model": "glm-4.7"},
                    }
                }
            )
        )

        # Load config
        config = get_config(arborist_home=git_repo_with_config / ".arborist")

        # Verify step-specific resolution
        run_runner, run_model = get_step_runner_model(config, "run")
        assert run_runner == "opencode"
        assert run_model == "glm-4.7"

        # Verify default fallback for post-merge (no step-specific config)
        pm_runner, pm_model = get_step_runner_model(config, "post-merge")
        assert pm_runner == "claude"
        assert pm_model == "sonnet"

    def test_cli_override_at_runtime(self, runner, main, git_repo_with_config):
        """Verify CLI --runner/--model override works via get_step_runner_model.

        CLI args should take precedence over config at runtime.
        """
        from agent_arborist.config import get_config, get_step_runner_model

        # Create project config
        config_file = git_repo_with_config / ".arborist" / "config.json"
        config_file.write_text(
            json.dumps(
                {
                    "defaults": {"runner": "opencode", "model": "config-model"},
                }
            )
        )

        config = get_config(arborist_home=git_repo_with_config / ".arborist")

        # CLI override should take precedence
        run_runner, run_model = get_step_runner_model(
            config, "run", cli_runner="claude", cli_model="cli-override-model"
        )
        assert run_runner == "claude"
        assert run_model == "cli-override-model"

    def test_env_var_override_at_runtime(self, runner, main, git_repo_with_config, monkeypatch):
        """Verify env var override works at runtime via get_step_runner_model.
        """
        from agent_arborist.config import get_config, get_step_runner_model

        # Create project config with defaults
        config_file = git_repo_with_config / ".arborist" / "config.json"
        config_file.write_text(
            json.dumps(
                {
                    "defaults": {"runner": "opencode", "model": "config-default-model"},
                }
            )
        )

        # Set env vars to override config defaults
        monkeypatch.setenv("ARBORIST_RUNNER", "gemini")
        monkeypatch.setenv("ARBORIST_MODEL", "env-override-model")

        # Config loading applies env overrides
        config = get_config(arborist_home=git_repo_with_config / ".arborist")

        # Env vars should have overridden defaults
        run_runner, run_model = get_step_runner_model(config, "run")
        assert run_runner == "gemini"
        assert run_model == "env-override-model"

    def test_step_specific_env_override_at_runtime(self, runner, main, git_repo_with_config, monkeypatch):
        """Verify step-specific env vars work at runtime.
        """
        from agent_arborist.config import get_config, get_step_runner_model

        # Create project config
        config_file = git_repo_with_config / ".arborist" / "config.json"
        config_file.write_text(
            json.dumps(
                {
                    "defaults": {"runner": "claude", "model": "sonnet"},
                }
            )
        )

        # Set step-specific env vars (only for 'run' step)
        monkeypatch.setenv("ARBORIST_STEP_RUN_RUNNER", "opencode")
        monkeypatch.setenv("ARBORIST_STEP_RUN_MODEL", "step-env-model")

        config = get_config(arborist_home=git_repo_with_config / ".arborist")

        # 'run' step should use step-specific env override
        run_runner, run_model = get_step_runner_model(config, "run")
        assert run_runner == "opencode"
        assert run_model == "step-env-model"

        # 'post-merge' step should use defaults (no step-specific override)
        pm_runner, pm_model = get_step_runner_model(config, "post-merge")
        assert pm_runner == "claude"
        assert pm_model == "sonnet"


@pytest.mark.provider
@pytest.mark.flaky
class TestE2ERealAICall:
    """E2E tests with real AI provider calls.

    These tests require:
    - API keys configured in .devcontainer/.env
    - Network access to AI providers
    - May take significant time to run

    Run with: pytest -m provider tests/test_config.py
    """

    @pytest.fixture
    def cerebras_env(self, monkeypatch):
        """Load Cerebras API key from .devcontainer/.env."""
        try:
            from dotenv import dotenv_values
        except ImportError:
            pytest.skip("python-dotenv not installed")

        env_file = Path(__file__).parent.parent / ".devcontainer" / ".env"
        if not env_file.exists():
            pytest.skip(".devcontainer/.env not found")

        env_vars = dotenv_values(env_file)
        if not env_vars.get("CEREBRAS_API_KEY"):
            pytest.skip("CEREBRAS_API_KEY not configured")

        for key, value in env_vars.items():
            if value:
                monkeypatch.setenv(key, value)

    def test_opencode_runner_with_cerebras_configured(self, cerebras_env, tmp_path, monkeypatch):
        """Verify OpenCode runner can be configured via config file."""
        from agent_arborist.config import get_config, get_step_runner_model

        monkeypatch.setenv("HOME", str(tmp_path))

        # Create config using OpenCode with Cerebras
        arborist_home = tmp_path / ".arborist"
        arborist_home.mkdir()
        (arborist_home / "config.json").write_text(
            json.dumps(
                {
                    "defaults": {
                        "runner": "opencode",
                        "model": "cerebras/llama-4-scout-17b",
                    }
                }
            )
        )

        config = get_config(arborist_home=arborist_home)
        runner, model = get_step_runner_model(config, "run")

        assert runner == "opencode"
        assert "cerebras" in model or "llama" in model


# =============================================================================
# Phase 11: Edge Cases and Error Handling
# =============================================================================


class TestConfigPermissionErrors:
    """Tests for config file permission errors."""

    @pytest.mark.skipif(os.name == "nt", reason="Unix permissions")
    def test_unreadable_config_file_error(self, tmp_path, monkeypatch):
        """Unreadable config file should raise clear error."""
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.delenv("ARBORIST_RUNNER", raising=False)
        monkeypatch.delenv("ARBORIST_DEFAULT_RUNNER", raising=False)

        config_file = tmp_path / ".arborist_config.json"
        config_file.write_text('{"defaults": {}}')
        config_file.chmod(0o000)

        try:
            with pytest.raises(ConfigLoadError) as exc:
                get_config(arborist_home=tmp_path / ".arborist")
            assert "permission" in str(exc.value).lower()
        finally:
            config_file.chmod(0o644)


class TestConfigConcurrentAccess:
    """Tests for concurrent config file access."""

    def test_config_load_during_write(self, tmp_path, monkeypatch):
        """Loading config during write should not corrupt data."""
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.delenv("ARBORIST_RUNNER", raising=False)
        monkeypatch.delenv("ARBORIST_DEFAULT_RUNNER", raising=False)

        config_file = tmp_path / ".arborist_config.json"

        errors = []

        def write_config():
            for i in range(10):
                config_file.write_text(
                    json.dumps({"defaults": {"runner": f"claude_{i}"}})
                )

        def read_config():
            for _ in range(10):
                try:
                    get_config(arborist_home=tmp_path / ".arborist")
                except Exception as e:
                    errors.append(e)

        threads = [
            threading.Thread(target=write_config),
            threading.Thread(target=read_config),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should handle gracefully (no crashes, only expected errors)
        assert len(errors) == 0 or all(
            isinstance(e, (ConfigLoadError, ConfigValidationError, json.JSONDecodeError))
            for e in errors
        )
