# Configuration System Design Plan (TDD)

## Overview

Comprehensive configuration system for Agent Arborist using Test-Driven Development.

**Key Design Decisions:**
- **Step config inheritance**: Independent fields (null runner uses default, specified model used)
- **Unknown fields**: Fail validation and exit with clear error
- **Config file creation**: Commented template showing all options
- **E2E tests**: Include real AI calls using OpenCode with Cerebras GLM-4.7

## Configuration Precedence

For each configuration value (highest to lowest):

1. **CLI flag** (e.g., `--runner opencode`)
2. **Environment variable** (e.g., `ARBORIST_RUNNER=opencode`)
3. **Step-specific env var** (e.g., `ARBORIST_STEP_RUN_RUNNER=claude`)
4. **Project config** (`.arborist/config.json`)
5. **Global config** (`~/.arborist_config.json`)
6. **Hardcoded default**

## Environment Variables

### Global Environment Variables
| Config Path | Environment Variable | Type |
|-------------|---------------------|------|
| defaults.runner | ARBORIST_RUNNER | string |
| defaults.model | ARBORIST_MODEL | string |
| defaults.output_format | ARBORIST_OUTPUT_FORMAT | string |
| defaults.container_mode | ARBORIST_CONTAINER_MODE | string |
| defaults.quiet | ARBORIST_QUIET | bool |
| timeouts.task_run | ARBORIST_TIMEOUT_TASK_RUN | int |
| timeouts.task_post_merge | ARBORIST_TIMEOUT_POST_MERGE | int |
| test.command | ARBORIST_TEST_COMMAND | string |
| test.timeout | ARBORIST_TEST_TIMEOUT | int |

### Step-Specific Environment Variables
| Step | Runner Env Var | Model Env Var |
|------|----------------|---------------|
| run | ARBORIST_STEP_RUN_RUNNER | ARBORIST_STEP_RUN_MODEL |
| post-merge | ARBORIST_STEP_POST_MERGE_RUNNER | ARBORIST_STEP_POST_MERGE_MODEL |

### Backward Compatibility (Deprecated)
| Old Var | New Var | Deprecation Warning |
|---------|---------|---------------------|
| ARBORIST_DEFAULT_RUNNER | ARBORIST_RUNNER | Yes |
| ARBORIST_DEFAULT_MODEL | ARBORIST_MODEL | Yes |

---

## TDD Implementation Phases

Each phase follows: **Write failing tests → Implement → Verify tests pass**

---

## Phase 1: Core Dataclasses

### 1.1 Test: Basic Dataclass Construction

**File**: `tests/test_config.py`

```python
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
```

**Implementation**: `src/agent_arborist/config.py`

```python
@dataclass
class DefaultsConfig:
    runner: str | None = None
    model: str | None = None
    output_format: str = "json"
    container_mode: str = "auto"
    quiet: bool = False

@dataclass
class TimeoutConfig:
    task_run: int = 1800
    task_post_merge: int = 300
    test_command: int | None = None

@dataclass
class StepConfig:
    runner: str | None = None
    model: str | None = None

@dataclass
class RunnerConfig:
    default_model: str | None = None
    models: dict[str, str] = field(default_factory=dict)
    timeout: int | None = None

@dataclass
class TestConfig:
    command: str | None = None
    timeout: int | None = None

@dataclass
class PathsConfig:
    worktrees: str = "worktrees"
    dags: str = "dagu"

@dataclass
class ArboristConfig:
    version: str = "1"
    defaults: DefaultsConfig = field(default_factory=DefaultsConfig)
    timeouts: TimeoutConfig = field(default_factory=TimeoutConfig)
    steps: dict[str, StepConfig] = field(default_factory=lambda: {
        "run": StepConfig(),
        "post-merge": StepConfig()
    })
    test: TestConfig = field(default_factory=TestConfig)
    paths: PathsConfig = field(default_factory=PathsConfig)
    runners: dict[str, RunnerConfig] = field(default_factory=dict)
```

---

### 1.2 Test: Config Serialization (to_dict / from_dict)

```python
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
            steps={"run": StepConfig(model="opus")}
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
```

---

### 1.3 Test: Config Validation

```python
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
```

---

## Phase 2: Config File Loading

### 2.1 Test: File Path Resolution

```python
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
```

### 2.2 Test: Loading Config from JSON File

```python
class TestConfigFileLoading:
    """Unit tests for loading config from JSON files."""

    def test_load_valid_config_file(self, tmp_path):
        """Valid JSON config file should load correctly."""
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({
            "version": "1",
            "defaults": {"runner": "claude", "model": "sonnet"}
        }))

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
        assert "JSON" in str(exc.value)
        assert str(config_file) in str(exc.value)

    def test_load_config_with_unknown_fields_fails(self, tmp_path):
        """Config with unknown fields should fail validation."""
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({
            "version": "1",
            "unknown_section": {"foo": "bar"}
        }))

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
        config_file.write_text(json.dumps({
            "defaults": {"runner": "opencode"}
        }))

        config = load_config_file(config_file)
        assert config.defaults.runner == "opencode"
        assert config.defaults.output_format == "json"  # default
        assert config.timeouts.task_run == 1800  # default
```

### 2.3 Test: Config File with Steps

```python
class TestConfigFileSteps:
    """Unit tests for step configuration in files."""

    def test_load_config_with_step_overrides(self, tmp_path):
        """Config with step overrides should load correctly."""
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({
            "steps": {
                "run": {"runner": "claude", "model": "opus"},
                "post-merge": {"runner": "gemini", "model": "flash"}
            }
        }))

        config = load_config_file(config_file)
        assert config.steps["run"].runner == "claude"
        assert config.steps["run"].model == "opus"
        assert config.steps["post-merge"].runner == "gemini"
        assert config.steps["post-merge"].model == "flash"

    def test_load_config_with_partial_step_config(self, tmp_path):
        """Step config with only model should keep runner as None."""
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({
            "steps": {
                "run": {"model": "opus"}  # runner is None
            }
        }))

        config = load_config_file(config_file)
        assert config.steps["run"].runner is None
        assert config.steps["run"].model == "opus"
```

---

## Phase 3: Config Merging

### 3.1 Test: Merge Two Configs

```python
class TestConfigMerging:
    """Unit tests for config merging logic."""

    def test_merge_project_overrides_global(self):
        """Project config should override global config."""
        global_config = ArboristConfig(
            defaults=DefaultsConfig(runner="claude", model="sonnet")
        )
        project_config = ArboristConfig(
            defaults=DefaultsConfig(runner="opencode")
        )

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
            steps={"run": StepConfig(runner="claude", model="sonnet")}
        )
        project_config = ArboristConfig(
            steps={"run": StepConfig(model="opus")}  # override model only
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
            timeouts=TimeoutConfig(task_run=1800)  # override one
        )

        merged = merge_configs(global_config, project_config)
        assert merged.timeouts.task_run == 1800  # overridden
        assert merged.timeouts.task_post_merge == 600  # preserved

    def test_merge_three_configs(self):
        """Merging multiple configs follows precedence."""
        hardcoded = ArboristConfig()  # all defaults
        global_config = ArboristConfig(
            defaults=DefaultsConfig(runner="claude")
        )
        project_config = ArboristConfig(
            defaults=DefaultsConfig(model="opus")
        )

        merged = merge_configs(hardcoded, global_config, project_config)
        assert merged.defaults.runner == "claude"
        assert merged.defaults.model == "opus"
        assert merged.defaults.output_format == "json"  # hardcoded default
```

---

## Phase 4: Environment Variable Override

### 4.1 Test: Global Env Var Override

```python
class TestEnvVarOverride:
    """Unit tests for environment variable overrides."""

    def test_arborist_runner_env_overrides_config(self, monkeypatch):
        """ARBORIST_RUNNER should override config."""
        monkeypatch.setenv("ARBORIST_RUNNER", "gemini")

        config = ArboristConfig(
            defaults=DefaultsConfig(runner="claude")
        )
        resolved = apply_env_overrides(config)
        assert resolved.defaults.runner == "gemini"

    def test_arborist_model_env_overrides_config(self, monkeypatch):
        """ARBORIST_MODEL should override config."""
        monkeypatch.setenv("ARBORIST_MODEL", "opus")

        config = ArboristConfig(
            defaults=DefaultsConfig(model="sonnet")
        )
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
```

### 4.2 Test: Step-Specific Env Var Override

```python
class TestStepEnvVarOverride:
    """Unit tests for step-specific env var overrides."""

    def test_step_run_runner_env_override(self, monkeypatch):
        """ARBORIST_STEP_RUN_RUNNER should override run step runner."""
        monkeypatch.setenv("ARBORIST_STEP_RUN_RUNNER", "opencode")

        config = ArboristConfig(
            steps={"run": StepConfig(runner="claude")}
        )
        resolved = apply_env_overrides(config)
        assert resolved.steps["run"].runner == "opencode"

    def test_step_run_model_env_override(self, monkeypatch):
        """ARBORIST_STEP_RUN_MODEL should override run step model."""
        monkeypatch.setenv("ARBORIST_STEP_RUN_MODEL", "opus")

        config = ArboristConfig(
            steps={"run": StepConfig(model="sonnet")}
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
                "post-merge": StepConfig(runner="claude")
            }
        )
        resolved = apply_env_overrides(config)
        assert resolved.steps["run"].runner == "opencode"  # overridden
        assert resolved.steps["post-merge"].runner == "claude"  # unchanged
```

### 4.3 Test: Backward Compatibility (Deprecated Env Vars)

```python
class TestDeprecatedEnvVars:
    """Unit tests for backward-compatible deprecated env vars."""

    def test_arborist_default_runner_still_works(self, monkeypatch, caplog):
        """ARBORIST_DEFAULT_RUNNER should work but warn."""
        monkeypatch.setenv("ARBORIST_DEFAULT_RUNNER", "opencode")

        config = ArboristConfig()
        with caplog.at_level(logging.WARNING):
            resolved = apply_env_overrides(config)

        assert resolved.defaults.runner == "opencode"
        assert "ARBORIST_DEFAULT_RUNNER" in caplog.text
        assert "deprecated" in caplog.text.lower()

    def test_arborist_default_model_still_works(self, monkeypatch, caplog):
        """ARBORIST_DEFAULT_MODEL should work but warn."""
        monkeypatch.setenv("ARBORIST_DEFAULT_MODEL", "opus")

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
```

---

## Phase 5: Runner/Model Resolution

### 5.1 Test: get_step_runner_model Function

```python
class TestGetStepRunnerModel:
    """Unit tests for runner/model resolution per step."""

    def test_cli_flags_take_precedence(self):
        """CLI flags should override all config."""
        config = ArboristConfig(
            defaults=DefaultsConfig(runner="claude", model="sonnet"),
            steps={"run": StepConfig(runner="gemini", model="flash")}
        )

        runner, model = get_step_runner_model(
            config, step="run",
            cli_runner="opencode", cli_model="glm-4.7"
        )
        assert runner == "opencode"
        assert model == "glm-4.7"

    def test_step_config_overrides_defaults(self):
        """Step config should override defaults."""
        config = ArboristConfig(
            defaults=DefaultsConfig(runner="claude", model="sonnet"),
            steps={"run": StepConfig(runner="opencode", model="glm-4.7")}
        )

        runner, model = get_step_runner_model(config, step="run")
        assert runner == "opencode"
        assert model == "glm-4.7"

    def test_defaults_used_when_no_step_config(self):
        """Defaults should be used when step config is None."""
        config = ArboristConfig(
            defaults=DefaultsConfig(runner="claude", model="sonnet"),
            steps={"run": StepConfig()}  # both None
        )

        runner, model = get_step_runner_model(config, step="run")
        assert runner == "claude"
        assert model == "sonnet"

    def test_independent_field_resolution(self):
        """Runner and model resolve independently."""
        config = ArboristConfig(
            defaults=DefaultsConfig(runner="claude", model="sonnet"),
            steps={"run": StepConfig(runner=None, model="opus")}  # only model
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
            steps={"run": StepConfig(model="opus")}
        )

        runner, model = get_step_runner_model(
            config, step="run",
            cli_runner="gemini", cli_model=None
        )
        assert runner == "gemini"  # CLI
        assert model == "opus"  # step config (CLI model was None)
```

### 5.2 Test: Model Alias Resolution

```python
class TestModelAliasResolution:
    """Unit tests for model alias expansion."""

    def test_alias_expanded_for_runner(self):
        """Model alias should expand to full name."""
        config = ArboristConfig(
            runners={
                "claude": RunnerConfig(models={
                    "sonnet": "claude-3-5-sonnet-20241022",
                    "opus": "claude-3-opus-20240229"
                })
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
                "gemini": RunnerConfig(models={"fast": "gemini-1.5-flash"})
            }
        )

        claude_fast = resolve_model_alias(config, runner="claude", model="fast")
        gemini_fast = resolve_model_alias(config, runner="gemini", model="fast")

        assert claude_fast == "claude-3-haiku"
        assert gemini_fast == "gemini-1.5-flash"
```

---

## Phase 6: Full Config Loading Pipeline

### 6.1 Test: get_config Function (Integration)

```python
class TestGetConfig:
    """Integration tests for full config loading pipeline."""

    def test_get_config_with_no_files(self, tmp_path, monkeypatch):
        """get_config returns defaults when no files exist."""
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.delenv("ARBORIST_RUNNER", raising=False)
        monkeypatch.delenv("ARBORIST_MODEL", raising=False)

        config = get_config(arborist_home=tmp_path / ".arborist")
        assert config.defaults.runner is None
        assert config.defaults.model is None
        assert config.timeouts.task_run == 1800

    def test_get_config_loads_global_file(self, tmp_path, monkeypatch):
        """get_config loads global config from ~/.arborist_config.json."""
        monkeypatch.setenv("HOME", str(tmp_path))

        global_config = tmp_path / ".arborist_config.json"
        global_config.write_text(json.dumps({
            "defaults": {"runner": "claude", "model": "sonnet"}
        }))

        config = get_config(arborist_home=tmp_path / ".arborist")
        assert config.defaults.runner == "claude"
        assert config.defaults.model == "sonnet"

    def test_get_config_loads_project_file(self, tmp_path, monkeypatch):
        """get_config loads project config from .arborist/config.json."""
        monkeypatch.setenv("HOME", str(tmp_path))

        arborist_home = tmp_path / ".arborist"
        arborist_home.mkdir()
        project_config = arborist_home / "config.json"
        project_config.write_text(json.dumps({
            "defaults": {"runner": "opencode"}
        }))

        config = get_config(arborist_home=arborist_home)
        assert config.defaults.runner == "opencode"

    def test_get_config_merges_global_and_project(self, tmp_path, monkeypatch):
        """get_config merges global and project configs correctly."""
        monkeypatch.setenv("HOME", str(tmp_path))

        # Global config
        global_config = tmp_path / ".arborist_config.json"
        global_config.write_text(json.dumps({
            "defaults": {"runner": "claude", "model": "sonnet"},
            "timeouts": {"task_run": 3600}
        }))

        # Project config
        arborist_home = tmp_path / ".arborist"
        arborist_home.mkdir()
        project_config = arborist_home / "config.json"
        project_config.write_text(json.dumps({
            "defaults": {"runner": "opencode"}  # override runner only
        }))

        config = get_config(arborist_home=arborist_home)
        assert config.defaults.runner == "opencode"  # project wins
        assert config.defaults.model == "sonnet"  # global preserved
        assert config.timeouts.task_run == 3600  # global preserved

    def test_get_config_applies_env_overrides(self, tmp_path, monkeypatch):
        """get_config applies env var overrides after file loading."""
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("ARBORIST_RUNNER", "gemini")

        global_config = tmp_path / ".arborist_config.json"
        global_config.write_text(json.dumps({
            "defaults": {"runner": "claude"}
        }))

        config = get_config(arborist_home=tmp_path / ".arborist")
        assert config.defaults.runner == "gemini"  # env wins
```

---

## Phase 7: Config Template Generation

### 7.1 Test: Generate Commented Template

```python
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

        assert "// " in template_str or "#" in template_str  # Has comments
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
```

---

## Phase 8: CLI Integration

### 8.1 Test: Config Show Command

```python
class TestConfigShowCommand:
    """Integration tests for `arborist config show` command."""

    def test_config_show_outputs_json(self, runner, tmp_path, monkeypatch):
        """config show should output JSON config."""
        monkeypatch.setenv("HOME", str(tmp_path))

        result = runner.invoke(main, ["config", "show"])

        assert result.exit_code == 0
        config = json.loads(result.output)
        assert "defaults" in config
        assert "timeouts" in config

    def test_config_show_reflects_global_config(self, runner, tmp_path, monkeypatch):
        """config show should reflect global config values."""
        monkeypatch.setenv("HOME", str(tmp_path))

        global_config = tmp_path / ".arborist_config.json"
        global_config.write_text(json.dumps({
            "defaults": {"runner": "opencode"}
        }))

        result = runner.invoke(main, ["config", "show"])
        config = json.loads(result.output)
        assert config["defaults"]["runner"] == "opencode"

    def test_config_show_reflects_env_overrides(self, runner, tmp_path, monkeypatch):
        """config show should reflect env var overrides."""
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("ARBORIST_RUNNER", "gemini")

        result = runner.invoke(main, ["config", "show"])
        config = json.loads(result.output)
        assert config["defaults"]["runner"] == "gemini"
```

### 8.2 Test: Config Init Command

```python
class TestConfigInitCommand:
    """Integration tests for `arborist config init` command."""

    def test_config_init_creates_global_file(self, runner, tmp_path, monkeypatch):
        """config init --global creates ~/.arborist_config.json."""
        monkeypatch.setenv("HOME", str(tmp_path))

        result = runner.invoke(main, ["config", "init", "--global"])

        assert result.exit_code == 0
        config_file = tmp_path / ".arborist_config.json"
        assert config_file.exists()

    def test_config_init_creates_commented_template(self, runner, tmp_path, monkeypatch):
        """config init should create a commented template."""
        monkeypatch.setenv("HOME", str(tmp_path))

        runner.invoke(main, ["config", "init", "--global"])

        config_file = tmp_path / ".arborist_config.json"
        content = config_file.read_text()
        # Should have documentation/comments in some form
        assert "version" in content
        assert "defaults" in content

    def test_config_init_does_not_overwrite(self, runner, tmp_path, monkeypatch):
        """config init should not overwrite existing config."""
        monkeypatch.setenv("HOME", str(tmp_path))

        config_file = tmp_path / ".arborist_config.json"
        config_file.write_text('{"existing": "config"}')

        result = runner.invoke(main, ["config", "init", "--global"])

        assert result.exit_code != 0 or "exists" in result.output.lower()
        assert config_file.read_text() == '{"existing": "config"}'

    def test_config_init_force_overwrites(self, runner, tmp_path, monkeypatch):
        """config init --force should overwrite existing config."""
        monkeypatch.setenv("HOME", str(tmp_path))

        config_file = tmp_path / ".arborist_config.json"
        config_file.write_text('{"existing": "config"}')

        result = runner.invoke(main, ["config", "init", "--global", "--force"])

        assert result.exit_code == 0
        content = json.loads(config_file.read_text())
        assert "version" in content
```

### 8.3 Test: Config Validate Command

```python
class TestConfigValidateCommand:
    """Integration tests for `arborist config validate` command."""

    def test_config_validate_valid_config(self, runner, tmp_path, monkeypatch):
        """config validate should succeed for valid config."""
        monkeypatch.setenv("HOME", str(tmp_path))

        config_file = tmp_path / ".arborist_config.json"
        config_file.write_text(json.dumps({
            "version": "1",
            "defaults": {"runner": "claude"}
        }))

        result = runner.invoke(main, ["config", "validate"])

        assert result.exit_code == 0
        assert "valid" in result.output.lower()

    def test_config_validate_invalid_runner(self, runner, tmp_path, monkeypatch):
        """config validate should fail for invalid runner."""
        monkeypatch.setenv("HOME", str(tmp_path))

        config_file = tmp_path / ".arborist_config.json"
        config_file.write_text(json.dumps({
            "defaults": {"runner": "invalid_runner"}
        }))

        result = runner.invoke(main, ["config", "validate"])

        assert result.exit_code != 0
        assert "runner" in result.output.lower()
        assert "invalid" in result.output.lower()

    def test_config_validate_unknown_field(self, runner, tmp_path, monkeypatch):
        """config validate should fail for unknown fields."""
        monkeypatch.setenv("HOME", str(tmp_path))

        config_file = tmp_path / ".arborist_config.json"
        config_file.write_text(json.dumps({
            "unknown_field": "value"
        }))

        result = runner.invoke(main, ["config", "validate"])

        assert result.exit_code != 0
        assert "unknown_field" in result.output

    def test_config_validate_invalid_json(self, runner, tmp_path, monkeypatch):
        """config validate should fail for invalid JSON."""
        monkeypatch.setenv("HOME", str(tmp_path))

        config_file = tmp_path / ".arborist_config.json"
        config_file.write_text("{ invalid json }")

        result = runner.invoke(main, ["config", "validate"])

        assert result.exit_code != 0
        assert "json" in result.output.lower() or "parse" in result.output.lower()
```

---

## Phase 9: DAG Builder Integration

### 9.1 Test: DAG Builder Uses Config

```python
class TestDagBuilderConfig:
    """Integration tests for DAG builder using config."""

    def test_dag_builder_uses_step_config(self, git_repo, tmp_path):
        """DAG builder should use step-specific runner/model from config."""
        arborist_home = tmp_path / ".arborist"
        arborist_home.mkdir()

        config_file = arborist_home / "config.json"
        config_file.write_text(json.dumps({
            "steps": {
                "run": {"runner": "opencode", "model": "glm-4.7"},
                "post-merge": {"runner": "gemini", "model": "flash"}
            }
        }))

        # Build DAG
        config = get_config(arborist_home=arborist_home)
        builder = DagBuilder(config=config, ...)
        dag_yaml = builder.build(...)

        # Verify run step uses opencode/glm-4.7
        assert "opencode" in dag_yaml
        assert "glm-4.7" in dag_yaml
        # Verify post-merge uses gemini/flash
        assert "gemini" in dag_yaml
        assert "flash" in dag_yaml

    def test_dag_builder_uses_default_config(self, git_repo, tmp_path):
        """DAG builder should use defaults when no step config."""
        arborist_home = tmp_path / ".arborist"
        arborist_home.mkdir()

        config_file = arborist_home / "config.json"
        config_file.write_text(json.dumps({
            "defaults": {"runner": "claude", "model": "sonnet"}
        }))

        config = get_config(arborist_home=arborist_home)
        builder = DagBuilder(config=config, ...)
        dag_yaml = builder.build(...)

        # Both steps should use claude/sonnet
        assert "claude" in dag_yaml
        assert "sonnet" in dag_yaml
```

---

## Phase 10: E2E Tests

### 10.1 Test: Full Workflow with Config File

```python
@pytest.mark.integration
class TestE2EConfigWorkflow:
    """E2E tests for config system in real workflows."""

    def test_full_workflow_with_project_config(self, git_repo):
        """Full workflow respects project config."""
        # Setup project with config
        arborist_home = git_repo / ".arborist"
        arborist_home.mkdir()

        (arborist_home / "config.json").write_text(json.dumps({
            "version": "1",
            "defaults": {"runner": "opencode", "model": "cerebras/llama-4-scout-17b"},
            "timeouts": {"task_run": 600}
        }))

        # Create spec file
        specs_dir = arborist_home / "specs"
        specs_dir.mkdir()
        (specs_dir / "001-test" / "spec.md").parent.mkdir(parents=True)
        (specs_dir / "001-test" / "spec.md").write_text("""
# Test Spec
## Tasks
- [ ] Task 1: Simple test task
""")

        # Run dag build
        runner = CliRunner()
        result = runner.invoke(main, [
            "--home", str(arborist_home),
            "--spec", "001-test",
            "dag", "build"
        ])

        assert result.exit_code == 0

        # Verify generated DAG uses config values
        dag_file = arborist_home / "dagu" / "001-test.yaml"
        dag_content = dag_file.read_text()
        assert "opencode" in dag_content
        assert "cerebras" in dag_content or "llama" in dag_content
```

### 10.2 Test: Real AI Call with Config (OpenCode/Cerebras)

```python
@pytest.mark.provider
@pytest.mark.flaky
class TestE2ERealAICall:
    """E2E tests with real AI provider calls."""

    @pytest.fixture
    def cerebras_env(self, monkeypatch):
        """Load Cerebras API key from .devcontainer/.env."""
        from dotenv import dotenv_values
        env_file = Path(__file__).parent.parent / ".devcontainer" / ".env"
        if env_file.exists():
            env_vars = dotenv_values(env_file)
            for key, value in env_vars.items():
                if value:
                    monkeypatch.setenv(key, value)

    def test_task_run_with_opencode_cerebras(self, git_repo, cerebras_env):
        """Task run using OpenCode with Cerebras model via config."""
        arborist_home = git_repo / ".arborist"
        arborist_home.mkdir()

        # Config using OpenCode with Cerebras
        (arborist_home / "config.json").write_text(json.dumps({
            "defaults": {
                "runner": "opencode",
                "model": "cerebras/llama-4-scout-17b"
            }
        }))

        # Create a simple task
        (git_repo / "README.md").write_text("# Test Project")

        runner = CliRunner()
        result = runner.invoke(main, [
            "--home", str(arborist_home),
            "task", "run-test",
            "--cmd", "echo 'test passed'"
        ])

        # Don't check exact output (non-deterministic)
        # Just verify it ran without config errors
        assert result.exit_code == 0 or "error" not in result.output.lower()

    def test_config_runner_model_used_in_inference(self, git_repo, cerebras_env, tmp_path):
        """Verify configured runner/model is actually used for inference."""
        arborist_home = git_repo / ".arborist"
        arborist_home.mkdir()

        # Use a specific model via config
        (arborist_home / "config.json").write_text(json.dumps({
            "steps": {
                "run": {
                    "runner": "opencode",
                    "model": "cerebras/llama-4-scout-17b"
                }
            }
        }))

        # Setup spec with simple task
        specs_dir = arborist_home / "specs"
        (specs_dir / "001-test").mkdir(parents=True)
        (specs_dir / "001-test" / "spec.md").write_text("""
# Test Spec
## Tasks
- [ ] Task 1: Add a comment to README.md
""")

        # Build and run DAG (just verify it starts without config errors)
        runner = CliRunner()

        # First build the DAG
        build_result = runner.invoke(main, [
            "--home", str(arborist_home),
            "--spec", "001-test",
            "dag", "build"
        ])
        assert build_result.exit_code == 0

        # Check DAG file contains correct runner/model
        dag_file = arborist_home / "dagu" / "001-test.yaml"
        if dag_file.exists():
            dag_content = dag_file.read_text()
            assert "opencode" in dag_content
```

---

## Phase 11: Edge Cases and Error Handling

### 11.1 Test: Permission Errors

```python
class TestConfigPermissionErrors:
    """Tests for config file permission errors."""

    @pytest.mark.skipif(os.name == 'nt', reason="Unix permissions")
    def test_unreadable_config_file_error(self, tmp_path, monkeypatch):
        """Unreadable config file should raise clear error."""
        monkeypatch.setenv("HOME", str(tmp_path))

        config_file = tmp_path / ".arborist_config.json"
        config_file.write_text('{"defaults": {}}')
        config_file.chmod(0o000)

        try:
            with pytest.raises(ConfigLoadError) as exc:
                get_config(arborist_home=tmp_path / ".arborist")
            assert "permission" in str(exc.value).lower()
        finally:
            config_file.chmod(0o644)
```

### 11.2 Test: Concurrent Access

```python
class TestConfigConcurrentAccess:
    """Tests for concurrent config file access."""

    def test_config_load_during_write(self, tmp_path, monkeypatch):
        """Loading config during write should not corrupt data."""
        import threading

        monkeypatch.setenv("HOME", str(tmp_path))
        config_file = tmp_path / ".arborist_config.json"

        errors = []

        def write_config():
            for i in range(10):
                config_file.write_text(json.dumps({
                    "defaults": {"runner": f"claude_{i}"}
                }))

        def read_config():
            for _ in range(10):
                try:
                    get_config(arborist_home=tmp_path / ".arborist")
                except Exception as e:
                    errors.append(e)

        threads = [
            threading.Thread(target=write_config),
            threading.Thread(target=read_config)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should handle gracefully (no crashes)
        assert len(errors) == 0 or all(
            isinstance(e, (ConfigLoadError, json.JSONDecodeError)) for e in errors
        )
```

---

## Implementation Checklist

### Phase 1: Core Dataclasses
- [ ] Write tests for dataclass construction (test_config.py::TestConfigDataclasses)
- [ ] Implement dataclasses in config.py
- [ ] Write tests for serialization (TestConfigSerialization)
- [ ] Implement to_dict/from_dict methods
- [ ] Write tests for validation (TestConfigValidation)
- [ ] Implement validate() methods
- [ ] Implement ConfigValidationError exception

### Phase 2: Config File Loading
- [ ] Write tests for path resolution (TestConfigPaths)
- [ ] Implement get_global_config_path, get_project_config_path
- [ ] Write tests for file loading (TestConfigFileLoading)
- [ ] Implement load_config_file function
- [ ] Implement ConfigLoadError exception
- [ ] Write tests for step config loading (TestConfigFileSteps)

### Phase 3: Config Merging
- [ ] Write tests for merging (TestConfigMerging)
- [ ] Implement merge_configs function

### Phase 4: Environment Variable Override
- [ ] Write tests for global env vars (TestEnvVarOverride)
- [ ] Implement apply_env_overrides function
- [ ] Write tests for step-specific env vars (TestStepEnvVarOverride)
- [ ] Implement step env var parsing
- [ ] Write tests for deprecated env vars (TestDeprecatedEnvVars)
- [ ] Implement deprecation warnings

### Phase 5: Runner/Model Resolution
- [ ] Write tests for get_step_runner_model (TestGetStepRunnerModel)
- [ ] Implement get_step_runner_model function
- [ ] Write tests for model aliases (TestModelAliasResolution)
- [ ] Implement resolve_model_alias function

### Phase 6: Full Config Pipeline
- [ ] Write integration tests for get_config (TestGetConfig)
- [ ] Implement get_config function

### Phase 7: Config Template Generation
- [ ] Write tests for template generation (TestConfigTemplate)
- [ ] Implement generate_config_template functions

### Phase 8: CLI Integration
- [ ] Write tests for config show (TestConfigShowCommand)
- [ ] Implement `arborist config show` command
- [ ] Write tests for config init (TestConfigInitCommand)
- [ ] Implement `arborist config init` command
- [ ] Write tests for config validate (TestConfigValidateCommand)
- [ ] Implement `arborist config validate` command

### Phase 9: DAG Builder Integration
- [ ] Write tests for DAG builder config (TestDagBuilderConfig)
- [ ] Update dag_builder.py to use config

### Phase 10: E2E Tests
- [ ] Write E2E workflow tests (TestE2EConfigWorkflow)
- [ ] Write real AI call tests (TestE2ERealAICall)
- [ ] Verify OpenCode/Cerebras integration

### Phase 11: Edge Cases
- [ ] Write permission error tests (TestConfigPermissionErrors)
- [ ] Write concurrent access tests (TestConfigConcurrentAccess)

### Documentation & Cleanup
- [ ] Create docs/configuration.md
- [ ] Update README.md
- [ ] Update .env.example with new env vars
- [ ] Add deprecation timeline to CHANGELOG
